// Browser geolocation only after explicit user gesture.
// Coordinates rounded to ~1 km: no raw GPS precision is stored in our SQLite.
(() => {
  const btn = document.getElementById("geo-button");
  const form = document.getElementById("radar-filters");
  const status = document.getElementById("geo-status");
  if (!btn || !form || !status) return;
  btn.addEventListener("click", () => {
    if (!navigator.geolocation) {
      status.textContent = "Este navegador não oferece geolocalização.";
      return;
    }
    btn.disabled = true;
    status.textContent = "Solicitando permissão para usar sua localização...";
    navigator.geolocation.getCurrentPosition(
      (position) => {
        document.getElementById("geo-lat").value = position.coords.latitude.toFixed(2);
        document.getElementById("geo-lon").value = position.coords.longitude.toFixed(2);
        document.getElementById("sort-select").value = "distance";
        status.textContent = "Localização aproximada pronta. Ordenando por proximidade...";
        btn.disabled = false;
        form.requestSubmit();
      },
      (error) => {
        const reasons = {
          1: "Permissão de localização negada.",
          2: "Localização indisponível no dispositivo.",
          3: "Tempo esgotado para obter a posição."
        };
        status.textContent = reasons[error.code] || "Não foi possível acessar sua localização.";
        btn.disabled = false;
      },
      { enableHighAccuracy: false, maximumAge: 300000, timeout: 10000 }
    );
  });
})();
