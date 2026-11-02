import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
  name: "OpenCinema.Studio",
  setup() {
    app.extensionManager.registerSidebarTab({
      id: "open-cinema-studio", icon: "pi pi-video", title: "Open Cinema",
      tooltip: "Open Cinema film workspace", type: "custom",
      render(el) {
        el.replaceChildren();
        const panel = document.createElement("section");
        panel.style.cssText = "padding:24px;display:grid;gap:16px;line-height:1.6";
        const title = document.createElement("h2"); title.textContent = "Open Cinema";
        const intro = document.createElement("p");
        intro.textContent = "Take your film from story to screen. Plan your cast, direct shots, and shape the final cut in Studio. Your workflow stays here.";
        const status = document.createElement("p"); status.setAttribute("role", "status");
        const open = document.createElement("a"); open.textContent = "Open Studio ↗";
        open.target = "_blank"; open.rel = "noopener"; open.hidden = true;
        open.style.cssText = "display:block;background:#234f3d;color:white;padding:12px 16px;border-radius:8px;text-align:center;text-decoration:none";
        const retry = document.createElement("button"); retry.textContent = "Start Studio";
        const refresh = async () => {
          try {
            const response = await api.fetchApi('/open-cinema/status');
            if (!response.ok) throw new Error('Restart ComfyUI to activate the Studio companion.');
            const data = await response.json();
            status.textContent = data.message;
            const url = new URL(window.location.href); url.port = String(data.port);
            url.pathname = '/'; url.search = ''; url.hash = '';
            open.href = url.href; open.hidden = data.state !== 'ready';
            retry.hidden = data.state === 'ready' || data.state === 'starting';
            if (data.state === 'starting' && el.isConnected) setTimeout(refresh, 1500);
          } catch (error) { status.textContent = error.message; retry.hidden = false; }
        };
        retry.onclick = async () => {
          retry.disabled = true;
          try { await api.fetchApi('/open-cinema/start', {method:'POST'}); await refresh(); }
          catch (error) { status.textContent = error.message; }
          finally { retry.disabled = false; }
        };
        panel.append(title, intro, status, open, retry); el.append(panel); refresh();
      }
    });
  }
});
