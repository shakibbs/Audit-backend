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
