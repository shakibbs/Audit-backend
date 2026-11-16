// Start like the portal: light theme and a 248px sidebar. The top-bar button switches light / dark;
// the choice is remembered in this browser.
if (!localStorage.getItem('civThemeSet')) { localStorage.setItem('adminTheme', '"light"'); localStorage.setItem('civThemeSet', '1'); }
if (!localStorage.getItem('civSidebarSet')) { localStorage.setItem('sidebarWidth', '248'); localStorage.setItem('civSidebarSet', '1'); }

// The theme draws tabs above the page; on pages that ask for it, show them under the page heading instead.
document.addEventListener('DOMContentLoaded', function () {
  var tabs = document.getElementById('tabs-wrapper');
  var anchor = document.querySelector('[data-civ-tabs-after]');
  if (tabs && anchor) anchor.after(tabs);
});

// Lists: a click anywhere on a row opens it (same as clicking its name). Tick boxes, links and buttons keep their own job.
document.addEventListener('click', function (event) {
  var row = event.target.closest('#result_list tbody tr');
  if (!row || event.target.closest('a, button, input, select, label, textarea')) return;
  var link = row.querySelector('th a[href], td a[href]');
  if (!link) return;
  if (event.ctrlKey || event.metaKey) window.open(link.href, '_blank');
  else window.location.href = link.href;
});

// Date-only fields (start date, contract dates…) get no "You are N hours ahead" note: it only means something for a
// time of day (2026-10-23). Django adds the note when the page loads, so it is removed just after.
window.addEventListener('load', function () {
  setTimeout(function () {
    document.querySelectorAll('.timezonewarning').forEach(function (note) {
      var box = note.parentNode;
      if (box && box.querySelector('input.vDateField') && !box.querySelector('input.vTimeField')) note.remove();
    });
  }, 0);
});

// Row buttons (Test connection now, Send password link, Resend…) do their job and reload the page, which drops any
// change not saved yet (QA 2026-10-23). If something on the page changed, ask first.
function civFormState(form) {
  var parts = [];
  new FormData(form).forEach(function (value, name) {
    if (name === 'csrfmiddlewaretoken') return;
    parts.push(name + '=' + (typeof value === 'string' ? value : value.name + ':' + value.size));
  });
  return parts.join('&');
}
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('form').forEach(function (form) {
    if (form.querySelector('button[formaction].civ-btn')) form.dataset.civStart = civFormState(form);
  });
});
document.addEventListener('click', function (event) {
  var button = event.target.closest('button[formaction].civ-btn');
  if (!button || !button.form || button.form.dataset.civStart === undefined) return;
  if (button.hasAttribute('data-civ-keeps-form')) return;  // this button uses what was typed (quote request steps)
  if (civFormState(button.form) === button.form.dataset.civStart) return;
  var go = window.confirm('You have changes on this page that are not saved.\n\n'
    + 'Press Cancel, then Save, to keep them.\nPress OK to continue without saving: the changes will be lost.');
  if (!go) event.preventDefault();
}, true);

// "Please correct the errors below" says which tab holds the problem, and opens it (QA 2026-10-23: the reason sat
// on a tab nobody was looking at).
window.addEventListener('load', function () {
  var note = Array.from(document.querySelectorAll('p.errornote')).find(function (p) { return /correct the error/i.test(p.textContent); });
  if (!note) return;
  var tabs = [];
  document.querySelectorAll('div[id$="-group"]').forEach(function (group) {
    if (!group.querySelector('.errornote, .errorlist')) return;
    var link = document.querySelector('#tabs-wrapper a[href="#' + group.id.replace(/-group$/, '') + '"]');
    if (link && tabs.indexOf(link) === -1) tabs.push(link);
  });
  if (!tabs.length) return;
  note.textContent = note.textContent.trim().replace(/\.$/, '') + ': see the ' + tabs.map(function (a) { return a.textContent.trim().replace(/\s+\d+$/, ''); }).join(', ')
    + ' tab' + (tabs.length > 1 ? 's' : '') + '.';
  tabs[0].click();
});

// The page title above its tabs (owner, 2026-10-31): Unfold draws a page's tab bar first, so move the heading up.
document.addEventListener('DOMContentLoaded', function () {
  var content = document.getElementById('content');
  var head = content && content.querySelector('.civ-page-head');
  if (head && content.firstElementChild !== head && head.compareDocumentPosition(content.firstElementChild) & Node.DOCUMENT_POSITION_PRECEDING) {
    content.prepend(head);
  }
});

// After the first "Add a connection" click, the button says "Add another connection" (owner, 2026-11-07).
document.addEventListener('click', function (event) {
  var button = event.target.closest('a.add-row');
  if (!button) return;
  button.querySelectorAll('span').forEach(function (span) {
    if (!span.children.length) span.textContent = span.textContent.replace(/^Add an? /, 'Add another ');
  });
});

// An eye button inside every password box shows or hides what was typed; it starts hidden (owner, 2026-11-16).
// Covers the staff sign-in page, the welcome page, Change my password and any later password box.
var CIV_EYE = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
var CIV_EYE_OFF = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19M14.12 14.12a3 3 0 1 1-4.24-4.24M1 1l22 22"/>';
function civPasswordEyes() {
  document.querySelectorAll('input[type="password"]:not([data-civ-eye])').forEach(function (input) {
    input.setAttribute('data-civ-eye', '1');
    var box = document.createElement('span');
    box.className = 'civ-pw';
    input.parentNode.insertBefore(box, input);
    box.appendChild(input);
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'civ-pw-eye';
    function draw(shown) {
      button.setAttribute('aria-label', shown ? 'Hide password' : 'Show password');
      button.setAttribute('aria-pressed', shown ? 'true' : 'false');
      button.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (shown ? CIV_EYE_OFF : CIV_EYE) + '</svg>';
    }
    draw(false);
    button.addEventListener('click', function () {
      var shown = input.type === 'password';
      input.type = shown ? 'text' : 'password';
      draw(shown);
    });
    box.appendChild(button);
  });
}
document.addEventListener('DOMContentLoaded', civPasswordEyes);
document.addEventListener('htmx:afterSwap', civPasswordEyes);

// Load on hover (owner, 2026-11-16): when the mouse rests on a link for a moment, the browser fetches that page in the
// background, so the click opens it almost at once, like the client portal. Only plain pages: the dashboard, a list, an
// "add" page and a record's page. Never a download, a file, a photo, a password link or any link that does something:
// those all have more parts in their address and do not match. Browsers without this feature (Firefox, Safari) simply
// load pages as before.
(function () {
  if (!(window.HTMLScriptElement && HTMLScriptElement.supports && HTMLScriptElement.supports('speculationrules'))) return;
  var rules = document.createElement('script');
  rules.type = 'speculationrules';
  rules.textContent = JSON.stringify({
    prefetch: [{
      source: 'document',
      where: { or: [
        { href_matches: '/civ-admin/' },
        { href_matches: '/civ-admin/:app/:model/' },
        { href_matches: '/civ-admin/:app/:model/add/' },
        { href_matches: '/civ-admin/:app/:model/:id/change/' },
      ] },
      eagerness: 'moderate',
    }],
  });
  document.head.appendChild(rules);
})();
