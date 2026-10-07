"use client";

import { useRouter } from "next/navigation";
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import { ApiError, type LoginResponse, type UserMe, getMe, login, logout } from "@/lib/api";

// Key used to broadcast auth changes across tabs. The value is just a
// monotonically-increasing timestamp; listeners only care that it changed.
const AUTH_SYNC_KEY = "soc_copilot_auth_event";

interface AuthState {
  user: UserMe | null;
  loading: boolean;
  /** Password step. When MFA is pending the user is NOT signed in yet. */
  signIn: (email: string, password: string) => Promise<LoginResponse>;
  /** Called after a successful /auth/mfa/verify. */
  completeSignIn: (user: UserMe) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserMe | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await getMe());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
      } else {
        // Network failure or other — surface but don't crash.
        console.warn("auth refresh failed:", err);
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Cross-tab sync + revalidate on tab focus, so a logout in tab A bounces
  // tab B without waiting for a manual refresh.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === AUTH_SYNC_KEY) void refresh();
    };
    const onFocus = () => void refresh();
    window.addEventListener("storage", onStorage);
    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  const broadcast = () => {
    try {
      localStorage.setItem(AUTH_SYNC_KEY, String(Date.now()));
    } catch {
      /* ignore — storage may be disabled */
    }
  };

  const signIn = useCallback(async (email: string, password: string) => {
    const res = await login(email, password);
    if (!res.mfa_required && res.user) {
      setUser(res.user);
      broadcast();
    }
    return res;
  }, []);

  const completeSignIn = useCallback((u: UserMe) => {
    setUser(u);
    broadcast();
  }, []);

  const signOut = useCallback(async () => {
    await logout();
    setUser(null);
    broadcast();
  }, []);

  return (
    <Ctx.Provider value={{ user, loading, signIn, completeSignIn, signOut, refresh }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Wraps a page so unauthenticated users get bounced to /login.
 *
 * Returns the auth state plus a `ready` flag. Pages should bail out of
 * rendering interactive UI until `ready` is true; otherwise a logout in
 * another tab leaves the form mounted and clickable until the redirect
 * finishes resolving.
 */
export function useRequireAuth() {
  const auth = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!auth.loading && !auth.user) {
      router.replace("/login");
    }
  }, [auth.loading, auth.user, router]);
  return { ...auth, ready: !auth.loading && auth.user !== null };
}
