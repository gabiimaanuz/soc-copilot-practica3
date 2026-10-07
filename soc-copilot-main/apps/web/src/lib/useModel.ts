"use client";

import { useEffect, useState } from "react";

import { type ModelsInfo, getLLMSettings, getModels } from "@/lib/api";

const STORAGE_KEY = "soc:llm-model";

/** Shared hook: fetches the allowlist once, exposes the selected model and
 *  a setter.
 *
 *  Resolution order for the initial selection:
 *    1. User's server-side ``preferred_chat_model`` (set in /settings/llm).
 *    2. localStorage cache (lets you flip per-tab without persisting).
 *    3. Server default.
 *
 *  The selected model is sent on every /explain, /recommend and /chat call
 *  so users can switch when a model hits a quota wall. */
export function useModel() {
  const [info, setInfo] = useState<ModelsInfo | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Fetch allowlist + per-user preference in parallel. The settings
    // call may legitimately fail for unauthenticated users (e.g. landing
    // page); we tolerate that and fall back to localStorage.
    Promise.all([getModels(), getLLMSettings().catch(() => null)])
      .then(([m, s]) => {
        setInfo(m);
        const preferred = s?.preferred_chat_model;
        if (preferred && m.available.includes(preferred)) {
          setSelected(preferred);
          return;
        }
        const stored =
          typeof window !== "undefined"
            ? window.localStorage.getItem(STORAGE_KEY)
            : null;
        if (stored && m.available.includes(stored)) {
          setSelected(stored);
        } else {
          setSelected(m.default);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  function choose(model: string) {
    setSelected(model);
    try {
      window.localStorage.setItem(STORAGE_KEY, model);
    } catch {
      /* localStorage may be unavailable in private mode */
    }
  }

  return { info, selected, choose, error };
}
