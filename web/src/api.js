let baseUrl = "";

export function setBaseUrl(url) {
  baseUrl = (url || "").replace(/\/$/, "");
}

export function getBaseUrl() {
  return baseUrl;
}

function url(path) {
  if (!baseUrl) return path;
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function api(path, { method = "GET", token, body, headers = {} } = {}) {
  const opts = {
    method,
    headers: {
      Accept: "application/json",
      ...headers,
    },
  };
  if (token) opts.headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url(path), opts);
  } catch {
    throw new Error("Server unerreichbar (Netzwerk/Zertifikat).");
  }
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const detail = data?.detail || data?.error?.message || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export async function streamChat({ token, messages, chatId, onToken, onMeta }) {
  let res;
  try {
    res = await fetch(url("/v1/chat/completions"), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        messages,
        stream: true,
        chat_id: chatId,
      }),
    });
  } catch {
    throw new Error("Server unerreichbar (Netzwerk/Zertifikat).");
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(errText || `HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n");
    buffer = parts.pop() || "";
    for (const line of parts) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const data = trimmed.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      let obj;
      try {
        obj = JSON.parse(data);
      } catch {
        continue;
      }
      if (obj.eigeneai) {
        onMeta?.(obj.eigeneai);
        continue;
      }
      if (obj.error) {
        throw new Error(obj.error.message || "Inference-Fehler");
      }
      const delta = obj.choices?.[0]?.delta?.content;
      if (delta) onToken?.(delta);
    }
  }
}
