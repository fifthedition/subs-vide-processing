'use strict';
window.StudioIcons=(()=>{
  const paths={play:'<path d="m8 5 11 7-11 7Z"/>',pause:'<path d="M8 5v14M16 5v14"/>',
    split:'<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="m8.2 8.2 11 11M8.2 15.8 19 5"/>',
    merge:'<path d="M5 3v4a5 5 0 0 0 5 5h2M19 3v4a5 5 0 0 1-5 5h-2M12 12v9M8 17l4 4 4-4"/>',
    delete:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    previous:'<path d="m15 5-8 7 8 7"/>',next:'<path d="m9 5 8 7-8 7"/>',
    star:'<path d="m12 3 2.8 5.8 6.4.9-4.6 4.5 1.1 6.4-5.7-3-5.7 3 1.1-6.4L2.8 9.7l6.4-.9Z"/>',
    archive:'<path d="M4 8v13h16V8M2 3h20v5H2ZM9 12h6"/>',history:'<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v5l3 2"/>',
    mic:'<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/>',
    volume:'<path d="m11 4-6 5H2v6h3l6 5ZM15 8a5 5 0 0 1 0 8M18 5a9 9 0 0 1 0 14"/>',
    mute:'<path d="m11 4-6 5H2v6h3l6 5ZM16 9l6 6M22 9l-6 6"/>',
    loop:'<path d="m17 2 4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 0 1-3 3H3"/>',
    check:'<path d="m4 12 5 5L20 6"/>',undo:'<path d="M8 4 3 9l5 5M3 9h11a6 6 0 0 1 0 12"/>',
    expand:'<path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5"/>'};
  const svg=name=>'<svg class="studio-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'+(paths[name]||paths.play)+'</svg>';
  function button(button,name,label){if(!button)return;button.innerHTML=svg(name);button.title=label;button.setAttribute('aria-label',label);button.classList.add('studio-icon-button');}
  return {svg,button};
})();
