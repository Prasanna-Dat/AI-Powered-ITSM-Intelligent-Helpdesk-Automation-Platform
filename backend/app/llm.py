"""LLM layer: grounded answer generation with a Hugging Face open-source model.

Default model: Qwen/Qwen2.5-0.5B-Instruct (Apache-2.0, ~1 GB, runs on a normal laptop CPU, follows instructions well).
Fallback:      'extractive' mode - no LLM, the answer is the retrieved KB text itself (still 100% grounded).
"""
import logging

from app.config import settings

log = logging.getLogger("llm")

SYSTEM = (
    "You are an IT helpdesk assistant. Answer the employee's question using ONLY the context provided. "
    "Reply with short numbered steps. Do not add facts that are not in the context. "
    "If the context does not contain the answer, reply with exactly: INSUFFICIENT_INFORMATION"
)


class LLM:
    def __init__(self):
        self.backend = "extractive"
        self.model_name = "none (extractive fallback)"
        self._tok = self._model = None
        if settings.LLM_BACKEND in ("auto", "hf"):
            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer
                self._tok = AutoTokenizer.from_pretrained(settings.LLM_MODEL)
                self._model = AutoModelForCausalLM.from_pretrained(settings.LLM_MODEL)
                self._model.eval()
                self.backend, self.model_name = "huggingface", settings.LLM_MODEL
            except Exception as exc:                  # noqa: BLE001
                log.warning("LLM unavailable (%s) -> extractive fallback", exc)
                if settings.LLM_BACKEND == "hf":
                    raise

    def answer(self, question: str, chunks: list):
        """Returns (answer_text_or_None, generated_by). None means 'the KB does not contain the answer'."""
        if not chunks:
            return None, self.backend
        if self.backend == "huggingface":
            try:
                text = self._generate(question, chunks)
                if not text or "INSUFFICIENT_INFORMATION" in text:
                    return None, self.backend
                return text, self.backend
            except Exception as exc:                  # noqa: BLE001
                log.error("LLM generation failed (%s) -> extractive", exc)
        return self._extractive(chunks), "extractive"

    def _generate(self, question, chunks):
        import torch
        context = "\n\n".join(f"[{i + 1}] {c['title']} - {c['section']}\n{c['text']}" for i, c in enumerate(chunks))
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"}]
        prompt = self._tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._tok(prompt, return_tensors="pt")
        with torch.no_grad():
            out = self._model.generate(**inputs, max_new_tokens=260, do_sample=False)
        return self._tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()

    @staticmethod
    def _extractive(chunks):
        best = chunks[0]
        parts = [best["text"]]
        for c in chunks[1:2]:                        # add one more chunk only if from the same article
            if c["doc_id"] == best["doc_id"]:
                parts.append(c["text"])
        return f"From the approved article \"{best['title']}\" ({best['section']}):\n" + "\n".join(parts)
