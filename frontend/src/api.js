// Thin fetch wrappers around the backend API. All paths are proxied to FastAPI by Vite.

async function send(path, options = {}) {
  const resp = await fetch(`/api${path}`, options);
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return resp;
}

async function request(path, options = {}) {
  const resp = await send(path, options);
  return resp.status === 204 ? null : resp.json();
}

const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  search: (q, limit = 20) => request(`/search?${new URLSearchParams({ q, limit })}`),
  listPapers: () => request("/papers"),
  getPaper: (id) => request(`/papers/${id}`),
  savePaper: (meta) => request("/papers", json("POST", meta)),
  deletePaper: (id) => request(`/papers/${id}`, { method: "DELETE" }),
  // Resolves to { paper, created }; created is false when this exact PDF was already uploaded.
  uploadPdf: async (file) => {
    const form = new FormData();
    form.append("file", file);
    const resp = await send("/papers/upload", { method: "POST", body: form });
    return { paper: await resp.json(), created: resp.status === 201 };
  },
  summarize: (id, refresh = false) => request(`/papers/${id}/summary?refresh=${refresh}`, { method: "POST" }),
  messages: (id) => request(`/papers/${id}/messages`),
  ask: (id, question) => request(`/papers/${id}/ask`, json("POST", { question })),
};
