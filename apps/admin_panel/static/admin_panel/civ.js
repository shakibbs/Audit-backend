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
