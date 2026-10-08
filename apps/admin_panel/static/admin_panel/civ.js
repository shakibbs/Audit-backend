// Start like the portal: light theme and a 248px sidebar. The top-bar button switches light / dark;
// the choice is remembered in this browser.
if (!localStorage.getItem('civThemeSet')) { localStorage.setItem('adminTheme', '"light"'); localStorage.setItem('civThemeSet', '1'); }
if (!localStorage.getItem('civSidebarSet')) { localStorage.setItem('sidebarWidth', '248'); localStorage.setItem('civSidebarSet', '1'); }
