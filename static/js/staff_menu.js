/* staff_menu.js – Lógica del menú de operaciones para staff */

document.querySelectorAll("[data-disabled='1']").forEach(function(el){
  el.addEventListener("click", function(e){ e.preventDefault(); });
});
