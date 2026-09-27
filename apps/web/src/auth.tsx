import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { User, UserManager, WebStorageStateStore } from "oidc-client-ts";

import { getWebRuntimeConfig } from "./config";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: () => Promise<void>;
  completeLogin: () => Promise<void>;
  logout: () => Promise<void>;
  clear: () => Promise<void>;
  accessToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function createUserManager(): UserManager {
  const config = getWebRuntimeConfig();
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

export function AuthProvider({ children }: PropsWithChildren) {
  const manager = useMemo(createUserManager, []);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    void manager
      .getUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, [manager]);
  const clear = useCallback(async () => {
    await manager.removeUser();
    setUser(null);
  }, [manager]);
  const login = useCallback(() => manager.signinRedirect(), [manager]);
  const completeLogin = useCallback(async () => {
    setUser(await manager.signinRedirectCallback());
  }, [manager]);
  const logout = useCallback(() => manager.signoutRedirect(), [manager]);
  const accessToken = useCallback(
    async () => (await manager.getUser())?.access_token ?? null,
    [manager],
  );
  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, login, completeLogin, logout, clear, accessToken }),
    [user, loading, login, completeLogin, logout, clear, accessToken],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is required");
  return value;
}
