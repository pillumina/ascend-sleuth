(function () {
  const workbench = document.querySelector('.bw-workbench');
  if (!workbench) return;
  const buttons = Array.from(workbench.querySelectorAll('[data-bw-case]'));
  const panels = Array.from(workbench.querySelectorAll('[data-bw-panel]'));

  function select(button, moveFocus) {
    if (!button) return;
    const id = button.dataset.bwCase;
    buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    panels.forEach(panel => { panel.hidden = panel.id !== id; });
    if (moveFocus) {
      const active = panels.find(panel => panel.id === id);
      active.querySelector('h4').focus();
    }
  }

  workbench.addEventListener('click', event => {
    const button = event.target.closest('[data-bw-case]');
    if (button) select(button, matchMedia('(max-width: 610px)').matches);
  });
  document.querySelectorAll('[data-bw-jump]').forEach(link => {
    link.addEventListener('click', event => {
      const group = workbench.querySelector('.bw-group[data-kind="' + link.dataset.bwJump + '"]');
      const button = group?.querySelector('[data-bw-best="true"]') || group?.querySelector('[data-bw-case]');
      select(button, false);
      const section = workbench.closest('details.sec');
      if (section) section.open = true;
      event.preventDefault();
      (button || group || workbench).scrollIntoView({block: 'center'});
      if (button) button.focus({preventScroll: true});
    });
  });
})();
