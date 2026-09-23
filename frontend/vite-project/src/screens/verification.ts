/**
 * Copyright (c) 2026 Meldra AI Ltd / Tally Platform. All rights reserved.
 * Screen Controller: Zero-Trust Counterparty Proof Pack Verification Portal
 */

import { etpClient, ProofPackVerificationResponse } from '../api';

export function renderVerificationPortalHtml(): string {
  return `
    <div class="verification-portal-card" style="padding: 20px; background: var(--surface); border: 1px solid var(--line); border-radius: 6px;">
      <h3 style="margin-top: 0; color: var(--ink);">Zero-Trust Counterparty Verification Portal</h3>
      <p style="color: var(--ink-2); font-size: 13.5px; margin-bottom: 16px;">
        Upload or paste a Tally proof pack to cryptographically verify Merkle roots, RFC 3161 TSA timestamps, and sequence gap nonces without logging in or trusting our servers.
      </p>

      <div style="margin-bottom: 16px;">
        <label style="display: block; font-size: 12px; font-weight: 600; font-family: 'IBM Plex Mono', monospace; margin-bottom: 6px; color: var(--ink-3);">PASTE PROOF PACK JSON</label>
        <textarea id="tally-proof-pack-input" rows="6" style="width: 100%; box-sizing: border-box; font-family: 'IBM Plex Mono', monospace; font-size: 12px; padding: 10px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 4px; color: var(--ink);" placeholder='{"merkle_root": "0971c8a1...", "authenticated_anchor_digest": "0971c8a1...", "expected_readings": 48, "received_readings": 42}'></textarea>
      </div>

      <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 16px;">
        <button id="btn-verify-proof-pack" style="background: var(--accent); color: #ffffff; border: none; padding: 10px 18px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 13px;">Verify Cryptographic Proof</button>
        <button id="btn-load-sample-proof-pack" style="background: var(--surface-2); color: var(--ink); border: 1px solid var(--line); padding: 10px 14px; border-radius: 4px; font-size: 13px; cursor: pointer;">Load Sample Proof Pack</button>
      </div>

      <div id="tally-verification-result" style="display: none;"></div>
    </div>
  `;
}

export function initVerificationPortal(containerId: string): void {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = renderVerificationPortalHtml();

  const verifyBtn = document.getElementById('btn-verify-proof-pack');
  const sampleBtn = document.getElementById('btn-load-sample-proof-pack');
  const input = document.getElementById('tally-proof-pack-input') as HTMLTextAreaElement;
  const resultDiv = document.getElementById('tally-verification-result');

  if (sampleBtn && input) {
    sampleBtn.addEventListener('click', () => {
      input.value = JSON.stringify({
        "merkle_root": "0971c8a1ce81287ccbc95aa4f171a5f807fb13ea2118f56b99769459a64906ad",
        "authenticated_anchor_digest": "0971c8a1ce81287ccbc95aa4f171a5f807fb13ea2118f56b99769459a64906ad",
        "tsa_anchor_ref": "urn:tally:tsa:2026-09-22:MPAN-1200098765432",
        "expected_readings": 48,
        "received_readings": 42,
        "status": "ANCHORED_WITH_GAPS",
        "@context": "https://www.w3.org/ns/prov-one#",
        "prov:wasDerivedFrom": "urn:tally:snapshot:2026-09-22:MPAN-1200098765432"
      }, null, 2);
    });
  }

  if (verifyBtn && input && resultDiv) {
    verifyBtn.addEventListener('click', async () => {
      const raw = input.value.trim();
      if (!raw) {
        alert('Please paste a proof pack JSON before verifying.');
        return;
      }

      resultDiv.style.display = 'block';
      resultDiv.innerHTML = '<p style="color: var(--ink-3);">Verifying cryptographic proof pack against independent algorithms...</p>';

      try {
        const json = JSON.parse(raw);
        const res: ProofPackVerificationResponse = await etpClient.verifyProofPack(json);

        const badgeClass = res.status === 'VERIFIED' ? 'ok' : (res.status === 'ANCHORED_WITH_GAPS' ? 'warn' : 'crit');

        resultDiv.innerHTML = `
          <div style="padding: 16px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 6px; margin-top: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
              <span style="font-weight: 700; font-size: 14px; color: var(--ink);">Verification Result</span>
              <span class="chip ${badgeClass}">${res.status}</span>
            </div>
            <p style="margin: 0 0 6px 0; font-size: 13px;"><b>Cryptographic Root Verified:</b> ${res.verified ? '<span style="color: var(--ok); font-weight: 600;">YES (Match)</span>' : '<span style="color: var(--crit); font-weight: 600;">NO (Mismatch)</span>'}</p>
            <p style="margin: 0 0 6px 0; font-size: 13px;"><b>Expected Period Count:</b> ${res.expected_period_count} | <b>Observed Leaf Count:</b> ${res.observed_leaf_count}</p>
            <p style="margin: 0 0 6px 0; font-size: 13px;"><b>Sequence Gaps Detected:</b> <span style="color: var(--warn); font-weight: 600;">${res.sequence_gap_count} missing intervals</span></p>
            <p style="margin: 0 0 6px 0; font-size: 12px; font-family: 'IBM Plex Mono', monospace; color: var(--hash);"><b>Merkle Root:</b> ${res.merkle_root}</p>
            <p style="margin: 0 0 6px 0; font-size: 12px; font-family: 'IBM Plex Mono', monospace; color: var(--time);"><b>TSA Anchor Ref:</b> ${res.tsa_anchor_ref}</p>
            ${res['prov:wasDerivedFrom'] ? `<p style="margin: 0; font-size: 11px; font-family: 'IBM Plex Mono', monospace; color: var(--ink-3);"><b>W3C PROV-O Derivation:</b> ${res['prov:wasDerivedFrom']}</p>` : ''}
          </div>
        `;
      } catch (err: any) {
        resultDiv.innerHTML = `<div style="padding: 12px; background: var(--crit-soft); color: var(--crit); border-radius: 4px;">Verification Error: ${err.message}</div>`;
      }
    });
  }
}
