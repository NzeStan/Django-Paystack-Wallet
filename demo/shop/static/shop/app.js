// Minimal client for the wallet REST API - what a real web/mobile client does:
// session auth + CSRF, and a fresh Idempotency-Key on every POST.

const Wallet = (() => {
  const API = '/wallet/api/';

  function csrfToken() {
    const match = document.cookie.split('; ').find((c) => c.startsWith('csrftoken='));
    return match ? decodeURIComponent(match.split('=')[1]) : '';
  }

  function newKey() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'k-' + Date.now() + '-' + Math.random().toString(16).slice(2);
  }

  async function call(method, path, body, idempotencyKey) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET') {
      headers['X-CSRFToken'] = csrfToken();
      headers['Idempotency-Key'] = idempotencyKey || newKey();
    }
    const response = await fetch(API + path, {
      method, headers, credentials: 'same-origin',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await response.json(); } catch (e) { /* empty body */ }
    return { ok: response.ok, status: response.status, data, replayed: response.headers.get('Idempotent-Replayed') };
  }

  function errorText(data) {
    if (!data) return 'Request failed';
    if (typeof data === 'string') return data;
    if (data.detail) return Array.isArray(data.detail) ? data.detail.join(' ') : data.detail;
    return Object.entries(data).map(([field, errors]) =>
      `${field}: ${Array.isArray(errors) ? errors.join(' ') : JSON.stringify(errors)}`).join(' | ');
  }

  function money(value, currency) {
    const number = Number(value || 0);
    return `${currency || 'NGN'} ${number.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function notify(target, result, successText) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) return;
    el.className = 'result ' + (result.ok ? 'ok' : 'error');
    const code = result.data && result.data.code ? ` (${result.data.code})` : '';
    el.textContent = result.ok
      ? (successText || 'Done') + (result.replayed ? ' (replayed)' : '')
      : `${result.status}: ${errorText(result.data)}${code}`;
  }

  function formData(form) {
    const data = {};
    new FormData(form).forEach((value, key) => { if (value !== '') data[key] = value; });
    return data;
  }

  function txnRow(t) {
    const sign = t.direction === 'credit' ? '+' : '-';
    const who = t.counterparty ? ` · ${t.counterparty.tag || ''}` : (t.bank_account ? ` · ${t.bank_account.bank_name}` : '');
    return `<tr>
      <td>${new Date(t.created_at).toLocaleString()}</td>
      <td>${t.transaction_type_display}${who}<div class="muted">${t.description || ''}</div></td>
      <td class="amount ${t.direction}">${sign}${money(t.total_amount, t.currency)}</td>
      <td><span class="badge ${t.status}">${t.status_display}</span>${t.requires_otp ? ' <span class="badge pending">OTP</span>' : ''}</td>
      <td class="muted">${t.fees !== '0.00' ? 'fee ' + money(t.fees, t.currency) : ''}</td>
      <td class="muted mono">${t.reference}</td>
    </tr>`;
  }

  return { call, errorText, money, notify, formData, txnRow, newKey };
})();
