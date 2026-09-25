import { etpClient } from '../api';
import type { ProofPackVerificationResponse } from '../api';

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
      const samplePack = {
        "merkle_root": "0971c8a1ce81287ccbc95aa4f171a5f807fb13ea2118f56b99769459a64906ad",
        "anchor_digest": "c6ae0e7b897931ee7e289ac121e42c55fa848d7c2f0fefbbcd960e653ee5c2fb",
        "first_nonce": 1000,
        "last_nonce": 1041,
        "prev_day_last_nonce": 999,
        "eod_gap": 6,
        "expected_readings": 48,
        "tsa_anchor_ref": "urn:tally:tsa:2026-09-22:MPAN-1200098765432",
        "@context": "https://www.w3.org/ns/prov-one#",
        "prov:wasDerivedFrom": "urn:tally:snapshot:2026-09-22:MPAN-1200098765432",
        "readings": [
          {"mpan": "MPAN-1200098765432", "reading_kwh": 10.0, "timestamp": "2026-09-22T00:00:00.000Z", "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000", "etp_nonce": 1000, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "1f145bd697f44d967781afccaebc44ea04b6b4e821ab9171441454d1502a5e41"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 10.5, "timestamp": "2026-09-22T00:30:00.000Z", "prev_hash": "1f145bd697f44d967781afccaebc44ea04b6b4e821ab9171441454d1502a5e41", "etp_nonce": 1001, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "f626dbbc38f6b43cd773fbb3677d2427a9cf60a3733c7fbe8d73b5c879d722d7"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 11.0, "timestamp": "2026-09-22T01:00:00.000Z", "prev_hash": "f626dbbc38f6b43cd773fbb3677d2427a9cf60a3733c7fbe8d73b5c879d722d7", "etp_nonce": 1002, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "f6aa3d3ae0bfbd7fca1ca9574d22c9e782d43e5a5cfa79afc91713437a346571"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 11.5, "timestamp": "2026-09-22T01:30:00.000Z", "prev_hash": "f6aa3d3ae0bfbd7fca1ca9574d22c9e782d43e5a5cfa79afc91713437a346571", "etp_nonce": 1003, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "d17f4ebbe99cf4b162fb1aa3758364ffbbffeb2bf784b8ae0ec9e1fe3c6cf715"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 12.0, "timestamp": "2026-09-22T02:00:00.000Z", "prev_hash": "d17f4ebbe99cf4b162fb1aa3758364ffbbffeb2bf784b8ae0ec9e1fe3c6cf715", "etp_nonce": 1004, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "b2e53526a6c25ebecffb7bdffbeecb3fbcbd140c83a9926cdfc9bd0bcf00e12d"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 12.5, "timestamp": "2026-09-22T02:30:00.000Z", "prev_hash": "b2e53526a6c25ebecffb7bdffbeecb3fbcbd140c83a9926cdfc9bd0bcf00e12d", "etp_nonce": 1005, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "63fb2faeac9908cfec25d31481b67270e5b53d4c062c3e1e9a7e089fa2d2a4f4"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 13.0, "timestamp": "2026-09-22T03:00:00.000Z", "prev_hash": "63fb2faeac9908cfec25d31481b67270e5b53d4c062c3e1e9a7e089fa2d2a4f4", "etp_nonce": 1006, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "a705a0c79cd8c73c126c6034a4debf6cc47e95531436a90cc2e107554f49ca31"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 13.5, "timestamp": "2026-09-22T03:30:00.000Z", "prev_hash": "a705a0c79cd8c73c126c6034a4debf6cc47e95531436a90cc2e107554f49ca31", "etp_nonce": 1007, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "91f7977fbe3e9e0346ac0e7f6c65153fd03c3478cc30c5405eb3ce79bf9ebee3"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 14.0, "timestamp": "2026-09-22T04:00:00.000Z", "prev_hash": "91f7977fbe3e9e0346ac0e7f6c65153fd03c3478cc30c5405eb3ce79bf9ebee3", "etp_nonce": 1008, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "643e5ffbb47e64b2f7635e1b0320370633c134545dcb2af746bcb9d36a587c63"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 14.5, "timestamp": "2026-09-22T04:30:00.000Z", "prev_hash": "643e5ffbb47e64b2f7635e1b0320370633c134545dcb2af746bcb9d36a587c63", "etp_nonce": 1009, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "5cff9138f08037c61fd6a33632f0ccf3a6d81c1162ce53526f998adccbb4e32b"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 15.0, "timestamp": "2026-09-22T05:00:00.000Z", "prev_hash": "5cff9138f08037c61fd6a33632f0ccf3a6d81c1162ce53526f998adccbb4e32b", "etp_nonce": 1010, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "d67a4e8c6746ecff5da2d9eecc5bde03eec3d36d4b64e1e6ee0e0384de2cfb16"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 15.5, "timestamp": "2026-09-22T05:30:00.000Z", "prev_hash": "d67a4e8c6746ecff5da2d9eecc5bde03eec3d36d4b64e1e6ee0e0384de2cfb16", "etp_nonce": 1011, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "79d0fc4dfe24f5b739aff7f5a638b1140b7eb1f3667ef0e23e922c29329e1a53"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 16.0, "timestamp": "2026-09-22T06:00:00.000Z", "prev_hash": "79d0fc4dfe24f5b739aff7f5a638b1140b7eb1f3667ef0e23e922c29329e1a53", "etp_nonce": 1012, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "418764b808b3828e85ed4e6a9bbeccab3245a7429f812c45c07232863ee6e457"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 16.5, "timestamp": "2026-09-22T06:30:00.000Z", "prev_hash": "418764b808b3828e85ed4e6a9bbeccab3245a7429f812c45c07232863ee6e457", "etp_nonce": 1013, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "1225d62c968c7a803e5f3d4c4c88431daea58da47cba30ec8ba1ef73d35137d5"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 17.0, "timestamp": "2026-09-22T07:00:00.000Z", "prev_hash": "1225d62c968c7a803e5f3d4c4c88431daea58da47cba30ec8ba1ef73d35137d5", "etp_nonce": 1014, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "5cc84f9ecfbc436e28f66aaf267275ba07cf29250dc35d661d9c7c8ff84fc38e"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 17.5, "timestamp": "2026-09-22T07:30:00.000Z", "prev_hash": "5cc84f9ecfbc436e28f66aaf267275ba07cf29250dc35d661d9c7c8ff84fc38e", "etp_nonce": 1015, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "f9acbfec15129573574f7fa0379fb3173c6ab74f0f22dc973f423a3394b6e851"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 18.0, "timestamp": "2026-09-22T08:00:00.000Z", "prev_hash": "f9acbfec15129573574f7fa0379fb3173c6ab74f0f22dc973f423a3394b6e851", "etp_nonce": 1016, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "20dc7539c1a891f07ee7826e30221e5b8de97ab751a046ffcb26598553671c73"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 18.5, "timestamp": "2026-09-22T08:30:00.000Z", "prev_hash": "20dc7539c1a891f07ee7826e30221e5b8de97ab751a046ffcb26598553671c73", "etp_nonce": 1017, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "f84159cdcd3fb30b76117c3d3f3203914a448d6b0d3dc58d6cafa58e67c0dd73"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 19.0, "timestamp": "2026-09-22T09:00:00.000Z", "prev_hash": "f84159cdcd3fb30b76117c3d3f3203914a448d6b0d3dc58d6cafa58e67c0dd73", "etp_nonce": 1018, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "6564c631e8c69bfb4971ec0c05af2d9cd02d959b84acf8a51ddc083f47d71cc4"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 19.5, "timestamp": "2026-09-22T09:30:00.000Z", "prev_hash": "6564c631e8c69bfb4971ec0c05af2d9cd02d959b84acf8a51ddc083f47d71cc4", "etp_nonce": 1019, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "3d06cb50aaf6df950da888e5ff39f2955415c0e073bc5bc5a6078c6b8e948111"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 20.0, "timestamp": "2026-09-22T10:00:00.000Z", "prev_hash": "3d06cb50aaf6df950da888e5ff39f2955415c0e073bc5bc5a6078c6b8e948111", "etp_nonce": 1020, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "e595f39e13740118d26d0acafd2d6a945e1d3ce02af6efce96fa3cd4f3148845"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 20.5, "timestamp": "2026-09-22T10:30:00.000Z", "prev_hash": "e595f39e13740118d26d0acafd2d6a945e1d3ce02af6efce96fa3cd4f3148845", "etp_nonce": 1021, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "7f988944d412b9f1b2fb5d9ade4ff84250c6b78cade67cbe0f0f7740e56d270b"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 21.0, "timestamp": "2026-09-22T11:00:00.000Z", "prev_hash": "7f988944d412b9f1b2fb5d9ade4ff84250c6b78cade67cbe0f0f7740e56d270b", "etp_nonce": 1022, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "3bf9b3b34c73dc6c552d3bb3fe399a573ad0ffcdb90d46b8c078ec02b278fe3a"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 21.5, "timestamp": "2026-09-22T11:30:00.000Z", "prev_hash": "3bf9b3b34c73dc6c552d3bb3fe399a573ad0ffcdb90d46b8c078ec02b278fe3a", "etp_nonce": 1023, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "6e09afb85f4e03cf7d375a90817530f2ab229af7c7d8c29eb180e73cbc8e6756"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 22.0, "timestamp": "2026-09-22T12:00:00.000Z", "prev_hash": "6e09afb85f4e03cf7d375a90817530f2ab229af7c7d8c29eb180e73cbc8e6756", "etp_nonce": 1024, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "4824d0010c4e6babbc690ca8a2d88dfa186e67aedc33357f9c4ff3ba91ba33e8"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 22.5, "timestamp": "2026-09-22T12:30:00.000Z", "prev_hash": "4824d0010c4e6babbc690ca8a2d88dfa186e67aedc33357f9c4ff3ba91ba33e8", "etp_nonce": 1025, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "fa65e73d4959cfe3172da3b3b75e1f4bf3f0eb0ccdb443ab71a9464e802c56d3"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 23.0, "timestamp": "2026-09-22T13:00:00.000Z", "prev_hash": "fa65e73d4959cfe3172da3b3b75e1f4bf3f0eb0ccdb443ab71a9464e802c56d3", "etp_nonce": 1026, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "855d24351e17bcfbeaf33b862c96e390c1086b6af110815e1110c141464a4b9a"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 23.5, "timestamp": "2026-09-22T13:30:00.000Z", "prev_hash": "855d24351e17bcfbeaf33b862c96e390c1086b6af110815e1110c141464a4b9a", "etp_nonce": 1027, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "669271c29108ffda8ef79b1344cf4c686208a15303afe63618dd4efb18049146"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 24.0, "timestamp": "2026-09-22T14:00:00.000Z", "prev_hash": "669271c29108ffda8ef79b1344cf4c686208a15303afe63618dd4efb18049146", "etp_nonce": 1028, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "80a3f0fb88f5ff21a5367596c4dc31c4ca7f43391a606f414d2dd3fe20780d17"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 24.5, "timestamp": "2026-09-22T14:30:00.000Z", "prev_hash": "80a3f0fb88f5ff21a5367596c4dc31c4ca7f43391a606f414d2dd3fe20780d17", "etp_nonce": 1029, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "631b5609345a050298a8f54e255ff3c0cedb9cb2e99ef386e49a39cc3c87b047"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 25.0, "timestamp": "2026-09-22T15:00:00.000Z", "prev_hash": "631b5609345a050298a8f54e255ff3c0cedb9cb2e99ef386e49a39cc3c87b047", "etp_nonce": 1030, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "34e903cbcf04929300fd78d97d475d45888f8f25c46acf5aad5b6eddac0adf14"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 25.5, "timestamp": "2026-09-22T15:30:00.000Z", "prev_hash": "34e903cbcf04929300fd78d97d475d45888f8f25c46acf5aad5b6eddac0adf14", "etp_nonce": 1031, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "3eaff5b3cf5bab7f1786780885aeeb556de0a22cb527a8e89c913d0f7e0198f1"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 26.0, "timestamp": "2026-09-22T16:00:00.000Z", "prev_hash": "3eaff5b3cf5bab7f1786780885aeeb556de0a22cb527a8e89c913d0f7e0198f1", "etp_nonce": 1032, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "fd1afbab26461fb9fa38567072207f0492dfbfb5861985b400142b8ec7cc458b"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 26.5, "timestamp": "2026-09-22T16:30:00.000Z", "prev_hash": "fd1afbab26461fb9fa38567072207f0492dfbfb5861985b400142b8ec7cc458b", "etp_nonce": 1033, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "f5bad26f95092aeab06ba0f0294cb41af4f6e564b9a4bdf2b5aef2a1c3a4c23a"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 27.0, "timestamp": "2026-09-22T17:00:00.000Z", "prev_hash": "f5bad26f95092aeab06ba0f0294cb41af4f6e564b9a4bdf2b5aef2a1c3a4c23a", "etp_nonce": 1034, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "cebabcc646cb7fc4a77204377d9b4a14f50795bec76958917188709890bdc009"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 27.5, "timestamp": "2026-09-22T17:30:00.000Z", "prev_hash": "cebabcc646cb7fc4a77204377d9b4a14f50795bec76958917188709890bdc009", "etp_nonce": 1035, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "5ebf2f4849841fe3ac3dddb13203a3ba201786cb45a591e26fc186dd4bf52e22"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 28.0, "timestamp": "2026-09-22T18:00:00.000Z", "prev_hash": "5ebf2f4849841fe3ac3dddb13203a3ba201786cb45a591e26fc186dd4bf52e22", "etp_nonce": 1036, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "339e42bfae5fc03e8b325391c31b25dc87fd8354ab1a817abfd5dae1e7daa5bd"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 28.5, "timestamp": "2026-09-22T18:30:00.000Z", "prev_hash": "339e42bfae5fc03e8b325391c31b25dc87fd8354ab1a817abfd5dae1e7daa5bd", "etp_nonce": 1037, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "8ceeb5fe5f233d74597d30271ce99661afe279dc71fbea9674e539848d072f9f"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 29.0, "timestamp": "2026-09-22T19:00:00.000Z", "prev_hash": "8ceeb5fe5f233d74597d30271ce99661afe279dc71fbea9674e539848d072f9f", "etp_nonce": 1038, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "bc3ff5050c7950d7446a45363c30930894d018a6419538cda70867d22d8f10c8"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 29.5, "timestamp": "2026-09-22T19:30:00.000Z", "prev_hash": "bc3ff5050c7950d7446a45363c30930894d018a6419538cda70867d22d8f10c8", "etp_nonce": 1039, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "f0931ef18ec741d867fcdaf80a6edd14df28b401b7d90a58cf96da4919020250"},
          {"mpan": "MPAN-1200098765432", "reading_kwh": 30.0, "timestamp": "2026-09-22T20:00:00.000Z", "prev_hash": "f0931ef18ec741d867fcdaf80a6edd14df28b401b7d90a58cf96da4919020250", "etp_nonce": 1040, "crypto_suite_id": "ECDSA-P256-SHA256-v1", "key_id": "k-test", "etp_block_hash": "14c5ffc75442841d0a4a55acfa20e86f6ec20e26d6a1e5175032191af2bbddfb"}
        ]
      };
      input.value = JSON.stringify(samplePack, null, 2);
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
