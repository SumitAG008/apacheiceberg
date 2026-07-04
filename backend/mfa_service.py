# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
# This software is proprietary and confidential. Unauthorised use is prohibited.
"""
mfa_service.py — Multi-Factor Authentication (MFA) notification service
Handles sending OTP codes via email (Resend.com).
"""
from __future__ import annotations

import os
import json
from typing import Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
APP_DOMAIN = os.environ.get("APP_DOMAIN", "https://meldra-lakeshouse.ai")
FROM_EMAIL = os.environ.get("MFA_FROM_EMAIL", "noreply@meldra-lakeshouse.ai")
FROM_NAME = os.environ.get("MFA_FROM_NAME", "Meldra AI")


def _build_otp_email_html(code: str, purpose: str = "login") -> str:
    action_label = {
        "login": "sign in to your account",
        "register": "verify your new account",
        "reset": "reset your password",
    }.get(purpose, "complete your action")

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your Meldra AI Security Code</title>
</head>
<body style="margin:0;padding:0;background:#0A0A14;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0A0A14;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
          
          <!-- Header -->
          <tr>
            <td align="center" style="padding-bottom:32px;">
              <div style="display:inline-flex;align-items:center;gap:10px;">
                <div style="width:36px;height:36px;background:linear-gradient(135deg,#7C3AED,#3B82F6);border-radius:10px;"></div>
                <span style="color:#fff;font-size:22px;font-weight:700;letter-spacing:-0.5px;">Meldra AI</span>
              </div>
            </td>
          </tr>
          
          <!-- Card -->
          <tr>
            <td style="background:#13131F;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:40px 36px;">
              
              <p style="color:#A78BFA;font-size:13px;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin:0 0 16px 0;">Security Code</p>
              <h1 style="color:#fff;font-size:24px;font-weight:700;margin:0 0 12px 0;line-height:1.3;">
                Your verification code
              </h1>
              <p style="color:#8B8BA7;font-size:15px;line-height:1.6;margin:0 0 32px 0;">
                Use this code to {action_label}. It expires in <strong style="color:#E2E2F0;">10 minutes</strong>.
              </p>
              
              <!-- OTP Code Box -->
              <div style="background:linear-gradient(135deg,rgba(124,58,237,0.15),rgba(59,130,246,0.15));border:1px solid rgba(124,58,237,0.3);border-radius:12px;padding:24px;text-align:center;margin:0 0 32px 0;">
                <span style="font-size:44px;font-weight:800;letter-spacing:12px;color:#fff;font-family:'Courier New',monospace;">{code}</span>
              </div>
              
              <p style="color:#8B8BA7;font-size:13px;line-height:1.6;margin:0;">
                If you didn't request this code, you can safely ignore this email. 
                Someone may have entered your email address by mistake.
              </p>
              
            </td>
          </tr>
          
          <!-- Footer -->
          <tr>
            <td align="center" style="padding-top:24px;">
              <p style="color:#4A4A6A;font-size:12px;margin:0;">
                &copy; 2025 Meldra AI Ltd. &bull; 
                <a href="{APP_DOMAIN}" style="color:#7C3AED;text-decoration:none;">{APP_DOMAIN}</a>
              </p>
              <p style="color:#4A4A6A;font-size:11px;margin:8px 0 0 0;">
                This is an automated security email. Please do not reply.
              </p>
            </td>
          </tr>
          
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def send_email_otp(to_email: str, code: str, purpose: str = "login") -> bool:
    """
    Send OTP code via Resend.com API.
    Returns True on success, raises RuntimeError on failure.
    """
    if not RESEND_API_KEY:
        print("\n" + "=" * 60)
        print(f"🔑 [DEV MODE] MFA OTP Code for {to_email}: {code}")
        print(f"Purpose: {purpose.upper()}")
        print("=" * 60 + "\n")
        return True

    subject_map = {
        "login": f"Your Meldra AI sign-in code: {code}",
        "register": f"Verify your Meldra AI account: {code}",
        "reset": f"Meldra AI password reset code: {code}",
    }

    payload = {
        "from": f"{FROM_NAME} <{FROM_EMAIL}>",
        "to": [to_email],
        "subject": subject_map.get(purpose, f"Meldra AI verification code: {code}"),
        "html": _build_otp_email_html(code, purpose),
        "text": (
            f"Your Meldra AI verification code is: {code}\n\n"
            f"This code expires in 10 minutes. Do not share it with anyone."
        ),
    }

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        if response.status_code not in (200, 201):
            error_detail = response.text
            raise RuntimeError(f"Resend API error {response.status_code}: {error_detail}")
        return True
    except httpx.TimeoutException:
        raise RuntimeError("Email delivery timed out. Please try again.")
    except httpx.RequestError as e:
        raise RuntimeError(f"Email delivery failed: {e}")
