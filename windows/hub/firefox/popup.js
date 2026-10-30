"use strict";
async function tell(type) {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (tab) await browser.tabs.sendMessage(tab.id, { type }).catch(() => {});
  window.close();
}
document.getElementById("draw").onclick = () => tell("draw");
document.getElementById("undraw").onclick = () => tell("undraw");
