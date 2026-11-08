// Small UX helpers used across the site.
document.addEventListener("DOMContentLoaded", function () {
  // Confirm dialogs: <form data-confirm="Are you sure?">
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!window.confirm(f.dataset.confirm)) e.preventDefault();
    });
  });

  // Auto-dismiss success/info alerts after a few seconds
  document.querySelectorAll(".alert-success, .alert-info").forEach(function (a) {
    setTimeout(function () {
      if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(a).close();
    }, 6000);
  });
});
