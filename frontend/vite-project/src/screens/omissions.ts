/**
 * Copyright (c) 2026 Meldra AI Ltd / Tally Platform. All rights reserved.
 * Screen Controller: Omission Register & 60-Second Telemetry Dispute Flow
 */

import { etpClient } from '../api';

export interface OmissionItem {
  mpan: string;
  day: string;
  gap_count: number;
  status: string;
  merkle_root: string;
  tsa_anchor_ref: string;
  built_at: string;
  expected_period_count?: number;
  observed_leaf_count?: number;
  '@context'?: string;
  'prov:wasDerivedFrom'?: string;
}

export function renderOmissionRegisterHtml(omissions: OmissionItem[]): string {
  if (!omissions || omissions.length === 0) {
    return `
      <div class="omission-empty-card" style="padding: 24px; text-align: center; background: var(--surface); border: 1px solid var(--line); border-radius: 6px;">
        <p style="color: var(--ink-3); margin: 0;">Zero telemetry gaps recorded. All sequence nonces complete.</p>
      </div>
    `;
  }

  const rows = omissions.map(item => `
    <tr>
      <td class="m id">${item.mpan}</td>
      <td class="m">${item.day}</td>
      <td class="m bad">${item.gap_count} SPs missing</td>
      <td>
        <span class="chip warn">GAPS (${item.observed_leaf_count || 42}/${item.expected_period_count || 48})</span>
      </td>
      <td class="m" style="font-size: 11px; color: var(--hash);">${item.merkle_root.substring(0, 16)}...</td>
      <td class="m" style="font-size: 11px; color: var(--time);">${item.tsa_anchor_ref}</td>
    </tr>
  `).join('');

  return `
    <div class="tbl-wrap" style="overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; background: var(--surface);">
      <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <thead>
          <tr style="background: var(--surface-2); text-transform: uppercase; font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--ink-3);">
            <th style="padding: 10px 12px; text-align: left;">Supply Point (MPAN)</th>
            <th style="padding: 10px 12px; text-align: left;">Date</th>
            <th style="padding: 10px 12px; text-align: left;">Sequence Gap</th>
            <th style="padding: 10px 12px; text-align: left;">Status</th>
            <th style="padding: 10px 12px; text-align: left;">Merkle Root</th>
            <th style="padding: 10px 12px; text-align: left;">TSA Reference</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
    </div>
  `;
}

export async function loadOmissionRegister(containerId: string): Promise<void> {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '<p style="color: var(--ink-3);">Loading Omission Register...</p>';

  try {
    const res = await etpClient.getOmissions();
    container.innerHTML = renderOmissionRegisterHtml(res.omissions);
  } catch (err: any) {
    container.innerHTML = `<p style="color: var(--crit);">Error loading omissions: ${err.message}</p>`;
  }
}

export async function runOmissionDemoController(buttonId: string, outputContainerId: string): Promise<void> {
  const btn = document.getElementById(buttonId) as HTMLButtonElement;
  const out = document.getElementById(outputContainerId);
  if (!btn || !out) return;

  btn.disabled = true;
  btn.textContent = 'Executing 60s Demo...';
  out.innerHTML = '<div style="padding: 12px; background: var(--surface-2); border-radius: 4px; font-family: monospace;">Simulating smart meter stream (48 readings)... Dropping 6 readings (12:00-15:00 UTC)... Computing Merkle tree...</div>';

  try {
    const result = await etpClient.run60sOmissionDemo();
    btn.disabled = false;
    btn.textContent = 'Re-Run 60-Second Omission Demo';

    out.innerHTML = `
      <div style="padding: 16px; background: var(--surface); border: 1px solid var(--accent); border-radius: 6px; margin-top: 12px;">
        <h4 style="margin: 0 0 8px 0; color: var(--accent); font-family: 'IBM Plex Mono', monospace;">${result.title}</h4>
        <p style="margin: 0 0 6px 0; font-size: 13px;"><b>Meter ID:</b> <code class="id">${result.meter_id}</code> | <b>Date:</b> ${result.date}</p>
        <p style="margin: 0 0 6px 0; font-size: 13px;"><b>Readings Received:</b> ${result.received_readings} / ${result.expected_readings} | <b>Omitted Count:</b> <span style="color: var(--warn); font-weight: 600;">${result.omitted_readings_count} SPs missing</span></p>
        <p style="margin: 0 0 6px 0; font-size: 13px;"><b>Checkpoint Status:</b> <span class="chip warn">${result.checkpoint_status}</span></p>
        <p style="margin: 0 0 6px 0; font-size: 12px; font-family: 'IBM Plex Mono', monospace; color: var(--hash);"><b>Merkle Root:</b> ${result.merkle_root}</p>
        <p style="margin: 0 0 6px 0; font-size: 12px; font-family: 'IBM Plex Mono', monospace; color: var(--time);"><b>TSA Anchor Ref:</b> ${result.tsa_anchor_ref}</p>
        <div style="margin-top: 10px; padding: 8px 12px; background: var(--accent-soft); border-left: 3px solid var(--accent); font-size: 12px; font-family: 'IBM Plex Mono', monospace;">
          <b>Verdict:</b> ${result.dispute_verdict} (Zero-trust cryptographic proof pack generated)
        </div>
      </div>
    `;
  } catch (err: any) {
    btn.disabled = false;
    btn.textContent = 'Run 60-Second Omission Demo';
    out.innerHTML = `<div style="padding: 12px; background: var(--crit-soft); color: var(--crit); border-radius: 4px;">Demo Failed: ${err.message}</div>`;
  }
}
