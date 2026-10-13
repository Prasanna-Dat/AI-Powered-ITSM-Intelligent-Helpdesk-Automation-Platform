---
id: KB0001
title: VPN Troubleshooting
category: Network
tags: vpn, authentication, remote access, connection
---
# VPN Troubleshooting

## Overview
Use this article when the corporate VPN client cannot connect or authentication keeps failing.

## Authentication failures
1. Confirm your network password has not expired. If it has expired, reset it first (see the Password Reset article).
2. Check that your account is not locked. Five wrong passwords lock the account for 30 minutes (see Account Unlock).
3. Make sure the time on your phone is correct, because multi-factor authentication (MFA) codes are time based. Re-sync the authenticator app if codes are rejected.
4. Close the VPN client completely and sign in again using the format DOMAIN\username.

## Connection failures
1. Check that your home or mobile internet works by opening any public website.
2. Restart the VPN client and choose the nearest gateway.
3. Turn off any third-party firewall or other VPN software.
4. Update the VPN client from the Software Center.

## VPN status check
The helpdesk can run a VPN status check that shows the gateway state and your last session. If the gateway shows online, the problem is on your device or account.

## When to raise a ticket
If the steps above do not work, raise an incident for Network Support with the exact error message, the time the problem started and your location.
