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
        panel.style.cssText = "padding:20px;display:grid;gap:12px;line-height:1.5;font-size:14px";
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
        const heading = document.createElement('h3'); heading.textContent = 'Models for this workflow';
        const explanation = document.createElement('p'); explanation.textContent = 'Check the open canvas. Only models used by its nodes are included.';
        const check = document.createElement('button'); check.textContent = 'Check workflow setup';
        const result = document.createElement('div'); result.setAttribute('aria-live', 'polite');
        const call = async (action, data) => {
          const response = await api.fetchApi('/open-cinema/setup/' + action, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
          const value = await response.json(); if(!response.ok) throw new Error(value.error || 'Setup check failed'); return value;
        };
        const inspect = async () => {
          check.disabled=true;
          try {
            const graph = (await app.graphToPrompt()).output;
            const data = await call('workflow', {graph});
            result.replaceChildren();
            const summary = document.createElement('p');
            summary.textContent=data.empty?'Open a workflow to check its models.':data.ready?'This workflow’s models and nodes are ready.':data.missing_ids.length?`${(data.missing_bytes/1e9).toFixed(1)} GB of models to install.`:'Check the requirements below.';
            result.append(summary);
            if(data.missing_nodes.length){const p=document.createElement('p');p.textContent='Missing nodes: '+data.missing_nodes.join(', ')+'. Update the relevant node packs, then restart ComfyUI.';result.append(p);}
            if(data.unmanaged_models.length){const p=document.createElement('p');p.textContent='Outside the Open Cinema catalog; check these in ComfyUI: '+data.unmanaged_models.join(', ');result.append(p);}
            const list=document.createElement('ul'); list.style.cssText='padding-left:18px;overflow-wrap:anywhere';
            for(const model of data.models){const li=document.createElement('li');li.style.marginBottom='10px';li.textContent=`${model.installed?'Installed':'Not installed'} · ${model.name}`;list.append(li);}
            const files=document.createElement('details'), filesTitle=document.createElement('summary');
            filesTitle.textContent=`Model files · ${data.models.length}`; filesTitle.style.cursor='pointer';
            files.append(filesTitle,list); if(data.models.length)result.append(files);
            const active=data.downloads.filter(j=>['queued','downloading','verifying'].includes(j.state));
            for(const job of data.downloads.filter(j=>data.models.some(m=>m.id===j.id))){const p=document.createElement('p');p.textContent=`${job.state} · ${(job.done/1e9).toFixed(1)} / ${(job.total/1e9).toFixed(1)} GB${job.error?' · '+job.error:''}`;result.append(p);}
            if(data.missing_ids.length){
              if(data.model_dir){const install=document.createElement('button');install.textContent=active.length?'Installing…':`Install required models · ${(data.missing_bytes/1e9).toFixed(1)} GB`;install.disabled=!!active.length;
                install.onclick=async()=>{install.disabled=true;try{await call('download',{ids:data.missing_ids});await inspect();}catch(error){summary.textContent=error.message;install.disabled=false;}};result.append(install);
              }else{const p=document.createElement('p');p.textContent='Open Studio → Setup to choose the model download folder.';result.append(p);}
            }
            if(active.length && el.isConnected) setTimeout(()=>{if(el.isConnected)inspect();},3000);
          } catch(error){result.textContent=error.message;} finally{check.disabled=false;}
        };
        check.onclick=inspect;
        for(const element of [title,intro,status,heading,explanation]) element.style.margin='0';
        heading.style.cssText='margin:16px 0 0;font-size:16px';
        check.style.cssText='padding:10px 12px;border-radius:8px;cursor:pointer';
        panel.append(title, intro, status, open, retry, heading, explanation, check, result); el.append(panel); refresh();
      }
    });
  }
});
