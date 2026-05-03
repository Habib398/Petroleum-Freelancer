document.addEventListener("DOMContentLoaded", ()=>{
  qs("#rmBtn").addEventListener("click", ()=>{
    const y = qs("#rmYear").value;
    const m = qs("#rmMonth").value;
    window.open(`/api/reports/monthly.pdf?year=${encodeURIComponent(y)}&month=${encodeURIComponent(m)}`,"_blank");
  });
  qs("#raBtn").addEventListener("click", ()=>{
    const y = qs("#raYear").value;
    window.open(`/api/reports/annual.pdf?year=${encodeURIComponent(y)}`,"_blank");
  });
});
