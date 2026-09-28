import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { getApps, initializeApp } from "firebase/app";
import {
  browserSessionPersistence,
  getAuth,
  onAuthStateChanged,
  setPersistence,
  signInWithEmailAndPassword,
  signOut,
  type Auth,
} from "firebase/auth";
import { User, UserManager, WebStorageStateStore } from "oidc-client-ts";

import {
  getWebRuntimeConfig,
  type IdentityPlatformWebRuntimeConfig,
  type WebRuntimeConfig,
} from "./config";

type AuthUser = User | { uid: string };

interface AuthContextValue {
  provider: "oidc" | "identity_platform";
  user: AuthUser | null;
  loading: boolean;
  login: (email?: string, password?: string) => Promise<void>;
  completeLogin: () => Promise<void>;
  logout: () => Promise<void>;
  clear: () => Promise<void>;
  accessToken: () => Promise<string | null>;
}

interface AuthBackend {
  provider: "oidc" | "identity_platform";
  subscribe: (listener: (user: AuthUser | null) => void) => () => void;
  login: (email?: string, password?: string) => Promise<void>;
  completeLogin: () => Promise<AuthUser | null>;
  logout: () => Promise<void>;
  clear: () => Promise<void>;
  accessToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function createUserManager(): UserManager {
  const config = getWebRuntimeConfig();
  if (config.authProvider !== "oidc")
    throw new Error("OIDC runtime configuration is required");
  return new UserManager({
    authority: config.oidcAuthority,
    client_id: config.oidcClientId,
    redirect_uri: config.oidcRedirectUri,
    post_logout_redirect_uri: config.oidcPostLogoutRedirectUri,
    scope: config.oidcScope,
    extraQueryParams: { audience: config.oidcAudience },
    response_type: "code",
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
}

export function createIdentityPlatformAuth(
  config: IdentityPlatformWebRuntimeConfig,
): Auth {
  const existing = getApps().find(
    (app) => app.name === "jewelai-identity-platform",
  );
  const app =
    existing ??
    initializeApp(
      {
        apiKey: config.identityPlatformApiKey,
        authDomain: config.identityPlatformAuthDomain,
        projectId: config.identityPlatformProjectId,
        appId: config.identityPlatformAppId,
      },
      "jewelai-identity-platform",
    );
  return getAuth(app);
}

function createBackend(config: WebRuntimeConfig): AuthBackend {
  if (config.authProvider === "identity_platform") {
    const auth = createIdentityPlatformAuth(config);
    const ready = setPersistence(auth, browserSessionPersistence);
    return {
      provider: "identity_platform",
      subscribe(listener) {
        let active = true;
        let unsubscribe = () => {};
        void ready
          .then(() => {
            if (!active) return;
            unsubscribe = onAuthStateChanged(auth, (user) =>
              listener(user ? { uid: user.uid } : null),
            );
          })
          .catch(() => {
            if (active) listener(null);
          });
        return () => {
          active = false;
          unsubscribe();
        };
      },
      async login(email, password) {
        if (!email || !password)
          throw new Error("Email and password are required");
        await ready;
        await signInWithEmailAndPassword(auth, email, password);
      },
      async completeLogin() {
        await ready;
        return auth.currentUser ? { uid: auth.currentUser.uid } : null;
      },
      async logout() {
        await ready;
        await signOut(auth);
      },
      async clear() {
        await ready;
        await signOut(auth);
      },
      async accessToken() {
        await ready;
        return (await auth.currentUser?.getIdToken()) ?? null;
      },
    };
  }
  const manager = createUserManager();
  return {
    provider: "oidc",
    subscribe(listener) {
      void manager
        .getUser()
        .then(listener)
        .catch(() => listener(null));
      return () => {};
    },
    async login() {
      await manager.signinRedirect();
    },
    async completeLogin() {
      return manager.signinRedirectCallback();
    },
    async logout() {
      await manager.signoutRedirect();
    },
    async clear() {
      await manager.removeUser();
    },
    async accessToken() {
      return (await manager.getUser())?.access_token ?? null;
    },
  };
}

export function AuthProvider({ children }: PropsWithChildren) {
  const backend = useMemo(() => createBackend(getWebRuntimeConfig()), []);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const unsubscribe = backend.subscribe((next) => {
      setUser(next);
      setLoading(false);
    });
    return unsubscribe;
  }, [backend]);
  const clear = useCallback(async () => {
    await backend.clear();
    setUser(null);
  }, [backend]);
  const login = useCallback(
    async (email?: string, password?: string) => backend.login(email, password),
    [backend],
  );
  const completeLogin = useCallback(async () => {
    setUser(await backend.completeLogin());
  }, [backend]);
  const logout = useCallback(async () => {
    await backend.logout();
    setUser(null);
  }, [backend]);
  const value = useMemo<AuthContextValue>(
    () => ({
      provider: backend.provider,
      user,
      loading,
      login,
      completeLogin,
      logout,
      clear,
      accessToken: backend.accessToken,
    }),
    [backend, user, loading, login, completeLogin, logout, clear],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is required");
  return value;
}
