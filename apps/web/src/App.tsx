import {
  QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  createContext,
  type FormEvent,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApiClient, ApiError } from "./api";
import { useAuth } from "./auth";
import { getWebRuntimeConfig } from "./config";
import { applyQuestionAnswer, type QuestionAnswer } from "./designUpdates";
import { AnswerForm } from "./forms";
import { clearOrganizationQueries, keys } from "./queryKeys";
import type {
  Asset,
  DesignRevision,
  DictionaryOption,
  Evaluation,
  GenerationRun,
  Me,
  MessageSource,
  Organization,
  Project,
  PromptRevision,
  Session,
  UiCatalog,
  VisualizationIteration,
  IterativeEditResponse,
  TextIntakeResponse,
} from "./types";

const ApiContext = createContext<ApiClient | null>(null);

function useApi(): ApiClient {
  const api = useContext(ApiContext);
  if (!api) throw new Error("API provider is required");
  return api;
}

function ApiProvider({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const navigate = useNavigate();
  const config = getWebRuntimeConfig();
  const api = useMemo(
    () =>
      new ApiClient(config.apiBaseUrl, auth.accessToken, async () => {
        await auth.clear();
        void navigate("/login", { replace: true });
      }),
    [auth, config.apiBaseUrl, navigate],
  );
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function IterativeEditForm({
  locale,
  activeEdit,
  loading,
  value,
  onChange,
  onSubmit,
}: {
  locale: string;
  activeEdit: boolean;
  loading: boolean;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <section className="panel intake-panel">
      <div>
        <p className="eyebrow">
          {locale === "ru"
            ? "Изменить выбранный вариант"
            : "Edit current visual"}
        </p>
        <h2>
          {locale === "ru" ? "Что нужно изменить?" : "What should change?"}
        </h2>
        <p>
          {activeEdit
            ? locale === "ru"
              ? "Ответьте на уточнение; остальные характеристики будут сохранены."
              : "Answer the clarification; all unmentioned characteristics stay unchanged."
            : locale === "ru"
              ? "Неупомянутые характеристики и заблокированные поля сохраняются."
              : "Unmentioned characteristics and locked fields remain unchanged."}
        </p>
      </div>
      <form className="intake-form" onSubmit={onSubmit}>
        <textarea
          aria-label={
            locale === "ru" ? "Запрос на изменение" : "Change request"
          }
          maxLength={4000}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={
            locale === "ru"
              ? "Например: Увеличьте центральный камень на 20%, остальное не меняйте."
              : "For example: Increase the center stone by 20%, but keep everything else unchanged."
          }
        />
        <button disabled={loading || !value.trim()} type="submit">
          {loading
            ? "Applying change…"
            : activeEdit
              ? "Continue edit"
              : "Apply change"}
        </button>
      </form>
    </section>
  );
}

function Protected() {
  const auth = useAuth();
  if (auth.loading)
    return <main className="centered">Loading secure session…</main>;
  return auth.user ? <Outlet /> : <Navigate to="/login" replace />;
}

function Login() {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (auth.user) return <Navigate to="/" replace />;
  return (
    <main className="login-page">
      <div className="brand-mark">J</div>
      <p className="eyebrow">JewelAI studio</p>
      <h1>Turn a jewelry idea into a precise design brief.</h1>
      <p>Sign in with your organization identity to continue.</p>
      {auth.provider === "identity_platform" ? (
        <form
          className="inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            setError(null);
            void auth
              .login(email, password)
              .catch(() => setError("Sign-in failed. Check your credentials."));
          }}
        >
          <label>
            Email
            <input
              required
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            Password
            <input
              required
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error ? <p role="alert">{error}</p> : null}
          <button className="primary" type="submit">
            Sign in securely
          </button>
        </form>
      ) : (
        <button className="primary" onClick={() => void auth.login()}>
          Sign in securely
        </button>
      )}
    </main>
  );
}

function Callback() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void auth
      .completeLogin()
      .then(() => navigate("/", { replace: true }))
      .catch(() =>
        setError("Sign-in could not be completed. Please try again."),
      );
  }, [auth, navigate]);
  return (
    <main className="centered">{error ?? "Completing secure sign-in…"}</main>
  );
}

function Shell() {
  const api = useApi();
  const auth = useAuth();
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const { data: me } = useQuery({
    queryKey: keys.me,
    queryFn: () => api.request<Me>("/me"),
  });
  const currentOrganization =
    /^\/organizations\/([^/]+)/.exec(location.pathname)?.[1] ?? "";
  return (
    <div className="shell">
      <header>
        <Link className="wordmark" to="/">
          JewelAI
        </Link>
        <div className="identity">
          {me?.memberships.length ? (
            <label className="organization-switcher">
              <span className="sr-only">Organization</span>
              <select
                aria-label="Organization"
                value={currentOrganization}
                onChange={(event) => {
                  if (currentOrganization) {
                    clearOrganizationQueries(client, currentOrganization);
                  }
                  void navigate(`/organizations/${event.target.value}`);
                }}
              >
                <option value="" disabled>
                  Choose organization
                </option>
                {me.memberships.map((membership) => (
                  <option
                    key={membership.organization_id}
                    value={membership.organization_id}
                  >
                    {membership.organization_name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <span>{me?.display_name ?? me?.email ?? "Signed in"}</span>
          <button className="quiet" onClick={() => void auth.logout()}>
            Log out
          </button>
        </div>
      </header>
      <Outlet />
    </div>
  );
}

function Dashboard() {
  const api = useApi();
  const client = useQueryClient();
  const navigate = useNavigate();
  const { data: me, isLoading } = useQuery({
    queryKey: keys.me,
    queryFn: () => api.request<Me>("/me"),
  });
  const [name, setName] = useState("");
  useEffect(() => {
    if (me?.memberships.length === 1 && me.memberships[0]) {
      void navigate(`/organizations/${me.memberships[0].organization_id}`, {
        replace: true,
      });
    }
  }, [me, navigate]);
  const create = useMutation({
    mutationFn: () =>
      api.request<Organization>("/organizations", {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    onSuccess: async () => {
      setName("");
      await client.invalidateQueries({ queryKey: keys.me });
    },
  });
  if (isLoading) return <main className="page">Loading organizations…</main>;
  return (
    <main className="page">
      <p className="eyebrow">Workspace</p>
      <h1>Your organizations</h1>
      {me?.memberships.length === 0 ? (
        <section className="empty">
          <h2>Create your first organization</h2>
          <p>
            An organization owns every project, design session, and private
            asset.
          </p>
        </section>
      ) : (
        <div className="card-grid">
          {me?.memberships.map((membership) => (
            <Link
              className="card"
              key={membership.organization_id}
              to={`/organizations/${membership.organization_id}`}
            >
              <span className="badge">{membership.role}</span>
              <h2>{membership.organization_name}</h2>
              <span>Open projects →</span>
            </Link>
          ))}
        </div>
      )}
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <label>
          Organization name
          <input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button type="submit">Create organization</button>
      </form>
    </main>
  );
}

function OrganizationProjects() {
  const api = useApi();
  const client = useQueryClient();
  const { organizationId = "" } = useParams();
  const [name, setName] = useState("");
  const { data } = useQuery({
    queryKey: keys.projects(organizationId),
    queryFn: () =>
      api.request<{ projects: Project[] }>(
        `/organizations/${organizationId}/projects`,
      ),
  });
  const create = useMutation({
    mutationFn: () =>
      api.request<Project>(`/organizations/${organizationId}/projects`, {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    onSuccess: async () => {
      setName("");
      await client.invalidateQueries({
        queryKey: keys.projects(organizationId),
      });
    },
  });
  return (
    <main className="page">
      <Breadcrumbs organizationId={organizationId} />
      <h1>Projects</h1>
      <div className="card-grid">
        {data?.projects.map((project) => (
          <Link
            className="card"
            key={project.project_id}
            to={`/organizations/${organizationId}/projects/${project.project_id}`}
          >
            <h2>{project.name}</h2>
            <span>View design sessions →</span>
          </Link>
        ))}
      </div>
      <form
        className="inline-form"
        onSubmit={(event) => submitName(event, create.mutate)}
      >
        <label>
          Project name
          <input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button type="submit">Create project</button>
      </form>
    </main>
  );
}

function ProjectSessions() {
  const api = useApi();
  const client = useQueryClient();
  const { organizationId = "", projectId = "" } = useParams();
  const catalog = useQuery({
    queryKey: keys.catalog,
    queryFn: () => api.request<UiCatalog>("/ui/catalog"),
  });
  const sessions = useQuery({
    queryKey: keys.sessions(organizationId, projectId),
    queryFn: () =>
      api.request<{ sessions: Session[] }>(`/projects/${projectId}/sessions`, {
        organizationId,
      }),
  });
  const [role, setRole] = useState("");
  const [locale, setLocale] = useState("");
  useEffect(() => {
    if (!role && catalog.data?.roles[0]) setRole(catalog.data.roles[0].role_id);
    if (!locale && catalog.data?.locales[0]) setLocale(catalog.data.locales[0]);
  }, [catalog.data, locale, role]);
  const create = useMutation({
    mutationFn: () =>
      api.request<Session>(`/projects/${projectId}/sessions`, {
        organizationId,
        method: "POST",
        body: JSON.stringify({ role_id: role, locale }),
      }),
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: keys.sessions(organizationId, projectId),
      });
    },
  });
  return (
    <main className="page">
      <Breadcrumbs organizationId={organizationId} />
      <h1>Design sessions</h1>
      <div className="card-grid">
        {sessions.data?.sessions.map((session) => (
          <Link
            className="card"
            key={session.session_id}
            to={`/organizations/${organizationId}/sessions/${session.session_id}`}
          >
            <span className="badge">{session.locale}</span>
            <h2>{humanize(session.role_id)}</h2>
            <span>Revision workspace →</span>
          </Link>
        ))}
      </div>
      <form
        className="inline-form"
        onSubmit={(event) => submitName(event, create.mutate)}
      >
        <label>
          Conversation role
          <select
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            {catalog.data?.roles.map((item) => (
              <option key={item.role_id} value={item.role_id}>
                {humanize(item.role_id)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Language
          <select
            value={locale}
            onChange={(event) => setLocale(event.target.value)}
          >
            {catalog.data?.locales.map((item) => (
              <option key={item} value={item}>
                {item.toUpperCase()}
              </option>
            ))}
          </select>
        </label>
        <button disabled={!role || !locale} type="submit">
          Start session
        </button>
      </form>
    </main>
  );
}

function Workspace() {
  const api = useApi();
  const client = useQueryClient();
  const { organizationId = "", sessionId = "" } = useParams();
  const scoped = { organizationId };
  const session = useQuery({
    queryKey: keys.workspace(organizationId, sessionId, "session"),
    queryFn: () => api.request<Session>(`/sessions/${sessionId}`, scoped),
  });
  const revision = useQuery({
    enabled: Boolean(session.data),
    queryKey: keys.workspace(
      organizationId,
      sessionId,
      `revision-${session.data?.current_revision_id ?? "pending"}`,
    ),
    queryFn: () =>
      api.request<DesignRevision>(
        `/sessions/${sessionId}/revisions/${session.data?.current_revision_id ?? ""}`,
        scoped,
      ),
  });
  const options = useQuery({
    queryKey: keys.workspace(organizationId, sessionId, "dictionary-options"),
    queryFn: () =>
      api.request<{ options: DictionaryOption[] }>(
        `/sessions/${sessionId}/dictionary-options`,
        scoped,
      ),
  });
  const assets = useQuery({
    queryKey: keys.workspace(organizationId, sessionId, "assets"),
    queryFn: () =>
      api.request<{ assets: Asset[] }>(`/sessions/${sessionId}/assets`, scoped),
  });
  const runs = useQuery({
    queryKey: keys.workspace(organizationId, sessionId, "runs"),
    queryFn: () =>
      api.request<{ generation_runs: GenerationRun[] }>(
        `/sessions/${sessionId}/generation-runs`,
        scoped,
      ),
  });
  const iterations = useQuery({
    queryKey: keys.workspace(
      organizationId,
      sessionId,
      "visualization-iterations",
    ),
    queryFn: () =>
      api.request<{ iterations: VisualizationIteration[] }>(
        `/sessions/${sessionId}/visualization-iterations`,
        scoped,
      ),
    refetchInterval: (query) =>
      query.state.data?.iterations.some((item) => item.status === "pending")
        ? 2_000
        : false,
  });
  const catalog = useQuery({
    queryKey: keys.catalog,
    queryFn: () => api.request<UiCatalog>("/ui/catalog"),
  });
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [intakeText, setIntakeText] = useState("");
  const [intakeLoading, setIntakeLoading] = useState(false);
  const [intakeIssues, setIntakeIssues] = useState<string[]>([]);
  const [editText, setEditText] = useState("");
  const [editLoading, setEditLoading] = useState(false);
  const [activeEditId, setActiveEditId] = useState<string | null>(null);
  const intakeInFlight = useRef(false);
  const [submittedRun, setSubmittedRun] = useState<GenerationRun | null>(null);
  const [submittedIteration, setSubmittedIteration] =
    useState<VisualizationIteration | null>(null);
  const [pollStarted, setPollStarted] = useState(() => Date.now());
  const [assetUrls, setAssetUrls] = useState<Record<string, string>>({});
  const listedActiveRun = (runs.data?.generation_runs ?? []).find((run) =>
    ["pending", "running"].includes(run.status),
  );
  const activeRunId =
    submittedRun?.generation_run_id ??
    listedActiveRun?.generation_run_id ??
    null;
  const active = useQuery({
    enabled: Boolean(activeRunId),
    queryKey: keys.workspace(
      organizationId,
      sessionId,
      `run-${activeRunId ?? "none"}`,
    ),
    queryFn: () =>
      api.request<GenerationRun>(
        `/sessions/${sessionId}/generation-runs/${activeRunId}`,
        scoped,
      ),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["succeeded", "failed"].includes(status)
        ? false
        : Date.now() - pollStarted >= 300_000
          ? false
          : 2_000;
    },
  });
  useEffect(() => {
    if (
      activeRunId &&
      active.data &&
      ["succeeded", "failed"].includes(active.data.status)
    ) {
      setSubmittedRun(null);
      void runs.refetch();
      void assets.refetch();
    }
  }, [active.data, activeRunId, assets, runs]);
  const listedActiveIteration = (iterations.data?.iterations ?? []).find(
    (item) => item.status === "pending",
  );
  const activeIteration = submittedIteration ?? listedActiveIteration ?? null;
  const currentVisualAssetId = [...(iterations.data?.iterations ?? [])]
    .reverse()
    .find((item) => item.current_visual_asset_id)?.current_visual_asset_id;
  useEffect(() => {
    const latest = iterations.data?.iterations.find(
      (item) => item.iteration_id === submittedIteration?.iteration_id,
    );
    if (latest && latest.status !== "pending") {
      setSubmittedIteration(null);
      void assets.refetch();
      void runs.refetch();
    }
  }, [assets, iterations.data, runs, submittedIteration?.iteration_id]);

  const refreshRevision = async () => {
    await client.invalidateQueries({
      queryKey: keys.workspace(organizationId, sessionId, "session"),
    });
    await session.refetch();
    await client.invalidateQueries({
      predicate: (query) =>
        query.queryKey[0] === "organization" &&
        query.queryKey[1] === organizationId &&
        query.queryKey[3] === sessionId,
    });
  };
  const evaluate = async () => {
    setError(null);
    setEvaluation(
      await api.request<Evaluation>(`/sessions/${sessionId}/evaluate`, {
        ...scoped,
        method: "POST",
        body: JSON.stringify({}),
      }),
    );
  };
  const submitTextIntake = async (event: FormEvent) => {
    event.preventDefault();
    if (!revision.data || !intakeText.trim() || intakeInFlight.current) return;
    intakeInFlight.current = true;
    setError(null);
    setIntakeIssues([]);
    setIntakeLoading(true);
    try {
      const result = await api.request<TextIntakeResponse>(
        `/sessions/${sessionId}/text-intake`,
        {
          ...scoped,
          method: "POST",
          body: JSON.stringify({
            expected_revision_id: revision.data.revision_id,
            content: intakeText.trim(),
          }),
        },
      );
      setIntakeText("");
      setEvaluation(result.evaluation);
      setIntakeIssues(result.proposal.issues.map((issue) => issue.detail));
      await refreshRevision();
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "stale_revision") {
        await refreshRevision();
        setError(
          "The design changed elsewhere. The latest revision has been loaded.",
        );
      } else if (
        caught instanceof ApiError &&
        [
          "text_understanding_unavailable",
          "text_understanding_invalid_response",
        ].includes(caught.code)
      ) {
        setError("Text understanding is temporarily unavailable. Try again.");
      } else if (caught instanceof ApiError) {
        setError(caught.message);
      } else {
        setError("The request could not be understood. Try again.");
      }
    } finally {
      intakeInFlight.current = false;
      setIntakeLoading(false);
    }
  };
  const answer = async (value: QuestionAnswer) => {
    if (!revision.data || !evaluation?.rendered_question) return;
    setError(null);
    const message = await api.request<{
      message_id: string;
      created_at: string;
    }>(`/sessions/${sessionId}/messages`, {
      ...scoped,
      method: "POST",
      body: JSON.stringify({
        content: `${evaluation.rendered_question.question_id}: ${JSON.stringify(value)}`,
      }),
    });
    const source: MessageSource = {
      kind: "message",
      message_id: message.message_id,
      recorded_at: message.created_at,
    };
    let proposedDesign;
    try {
      proposedDesign = applyQuestionAnswer(
        revision.data.design,
        evaluation.decision.concrete_target ??
          evaluation.rendered_question.target,
        value,
        source,
      );
    } catch {
      setError(
        "This question target is not supported by the v1 answer workflow.",
      );
      return;
    }
    try {
      await api.request(`/sessions/${sessionId}/revisions`, {
        ...scoped,
        method: "POST",
        body: JSON.stringify({
          action: "edit",
          expected_revision_id: revision.data.revision_id,
          proposed_design: proposedDesign,
          source,
          reason: `Answered ${evaluation.rendered_question.question_id}`,
        }),
      });
      setEvaluation(null);
      await refreshRevision();
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "stale_revision") {
        await refreshRevision();
        setError(
          "The design changed elsewhere. The latest revision has been loaded.",
        );
      } else if (
        caught instanceof ApiError &&
        caught.code === "locked_field_conflict"
      ) {
        setError("This field is locked and cannot be changed by this answer.");
      } else throw caught;
    }
  };
  const submitIterativeEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!revision.data || !editText.trim() || editLoading) return;
    setEditLoading(true);
    setError(null);
    try {
      const path = activeEditId
        ? `/sessions/${sessionId}/iterative-edits/${activeEditId}/messages`
        : `/sessions/${sessionId}/iterative-edits`;
      const result = await api.request<IterativeEditResponse>(path, {
        ...scoped,
        method: "POST",
        body: JSON.stringify({
          expected_revision_id: revision.data.revision_id,
          content: editText.trim(),
        }),
      });
      setEditText("");
      setEvaluation(result.evaluation);
      setIntakeIssues(result.proposal.issues.map((issue) => issue.detail));
      if (result.iteration) {
        setSubmittedIteration(result.iteration);
        setActiveEditId(null);
        await iterations.refetch();
      } else {
        setActiveEditId(result.edit_id);
      }
      await refreshRevision();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The change request failed safely.",
      );
    } finally {
      setEditLoading(false);
    }
  };
  if (!session.data || !revision.data)
    return <main className="page">Loading workspace…</main>;
  return (
    <main className="page workspace">
      <Breadcrumbs organizationId={organizationId} />
      <div className="workspace-heading">
        <div>
          <p className="eyebrow">{humanize(session.data.role_id)}</p>
          <h1>Design revision {revision.data.revision}</h1>
        </div>
        <span className="badge">{session.data.locale.toUpperCase()}</span>
      </div>
      {error && <div className="alert">{error}</div>}
      <section className="panel intake-panel">
        <div>
          <p className="eyebrow">
            {session.data.locale === "ru" ? "Текстовый запрос" : "Text request"}
          </p>
          <h2>
            {session.data.locale === "ru"
              ? "Опишите желаемое украшение"
              : "Describe the jewelry you want"}
          </h2>
        </div>
        <form
          className="intake-form"
          onSubmit={(event) => void submitTextIntake(event)}
        >
          <label>
            <span className="sr-only">
              {session.data.locale === "ru"
                ? "Описание украшения"
                : "Jewelry description"}
            </span>
            <textarea
              maxLength={4000}
              value={intakeText}
              onChange={(event) => setIntakeText(event.target.value)}
              placeholder={
                session.data.locale === "ru"
                  ? "Например: Хочу кольцо из белого золота с овальным центральным камнем."
                  : "For example: I want a white-gold ring with an oval center stone."
              }
            />
          </label>
          <button disabled={intakeLoading || !intakeText.trim()} type="submit">
            {intakeLoading
              ? session.data.locale === "ru"
                ? "Анализируем…"
                : "Understanding…"
              : session.data.locale === "ru"
                ? "Понять запрос"
                : "Understand request"}
          </button>
        </form>
        {intakeIssues.length > 0 && (
          <div className="notice" role="status">
            <strong>
              {session.data.locale === "ru"
                ? "Нужно уточнение:"
                : "Needs clarification:"}
            </strong>
            <ul>
              {intakeIssues.map((issue, index) => (
                <li key={`${index}-${issue}`}>{issue}</li>
              ))}
            </ul>
          </div>
        )}
      </section>
      <section className="panel question-panel">
        <div>
          <p className="eyebrow">Deterministic design check</p>
          <h2>
            {evaluation
              ? humanize(evaluation.decision.decision)
              : "What should we refine?"}
          </h2>
          <p>
            {evaluation?.rendered_question?.wording ??
              evaluation?.decision.reason}
          </p>
        </div>
        {!evaluation && (
          <button onClick={() => void evaluate()}>Evaluate design</button>
        )}
        {evaluation?.rendered_question && !activeEditId && (
          <AnswerForm
            contract={evaluation.rendered_question.answer_contract}
            options={options.data?.options ?? []}
            onSubmit={answer}
          />
        )}
        {evaluation?.decision.decision === "ready" && !activeEditId && (
          <ReadyActions
            api={api}
            organizationId={organizationId}
            sessionId={sessionId}
            revisionId={revision.data.revision_id}
            profiles={catalog.data?.generation_profiles ?? []}
            activeIteration={activeIteration}
            onIteration={(iteration) => {
              setSubmittedIteration(iteration);
              void iterations.refetch();
            }}
          />
        )}
        {evaluation &&
          evaluation.decision.decision !== "ask" &&
          evaluation.decision.decision !== "ready" && (
            <p className="notice">
              This proposal is informational and has not changed the revision.
            </p>
          )}
      </section>
      <div className="two-column">
        <section className="panel">
          <h2>Design summary</h2>
          <dl className="summary">
            <dt>Center stone shape</dt>
            <dd>{stateValue(revision.data.design.center_stone.shape)}</dd>
            <dt>Center stone setting</dt>
            <dd>{stateValue(revision.data.design.center_stone.setting)}</dd>
            <dt>Metal color</dt>
            <dd>{stateValue(revision.data.design.metal.color)}</dd>
          </dl>
          <details>
            <summary>Technical JSON</summary>
            <pre>{JSON.stringify(revision.data.design, null, 2)}</pre>
          </details>
        </section>
        <section className="panel">
          <h2>Generation runs</h2>
          {(runs.data?.generation_runs ?? []).map((run) => (
            <article className="list-row" key={run.generation_run_id}>
              <div>
                <strong>{humanize(run.status)}</strong>
                <small>
                  Attempt {run.attempt}
                  {run.parent_generation_run_id ? " · retry" : ""}
                </small>
              </div>
              {run.status === "failed" && (
                <button
                  className="quiet"
                  onClick={() =>
                    void api
                      .request<GenerationRun>(
                        `/sessions/${sessionId}/generation-runs/${run.generation_run_id}/retry`,
                        { ...scoped, method: "POST", body: JSON.stringify({}) },
                      )
                      .then((child) => {
                        setSubmittedRun(child);
                        setPollStarted(Date.now());
                        return runs.refetch();
                      })
                  }
                >
                  Retry
                </button>
              )}
            </article>
          ))}
          {activeRunId && Date.now() - pollStarted >= 300_000 && (
            <p className="notice">
              Live polling paused after five minutes. Refresh to check again.
            </p>
          )}
        </section>
      </div>
      <VisualizationIterationPanel
        api={api}
        organizationId={organizationId}
        sessionId={sessionId}
        locale={session.data.locale}
        iterations={iterations.data?.iterations ?? []}
        urls={assetUrls}
        onView={async (assetId) => {
          const access = await api.request<{ url: string }>(
            `/sessions/${sessionId}/assets/${assetId}/access`,
            {
              ...scoped,
              method: "POST",
              body: JSON.stringify({ ttl_seconds: 300 }),
            },
          );
          setAssetUrls((current) => ({ ...current, [assetId]: access.url }));
        }}
        onChanged={() => iterations.refetch()}
      />
      {currentVisualAssetId && (
        <IterativeEditForm
          locale={session.data.locale}
          activeEdit={Boolean(activeEditId)}
          loading={editLoading}
          value={editText}
          onChange={setEditText}
          onSubmit={(event) => void submitIterativeEdit(event)}
        />
      )}
      <AssetPanel
        assets={assets.data?.assets ?? []}
        urls={assetUrls}
        onUpload={async (file) => {
          const form = new FormData();
          form.set("file", file);
          await api.request(`/sessions/${sessionId}/assets`, {
            ...scoped,
            method: "POST",
            body: form,
          });
          await assets.refetch();
        }}
        onView={async (assetId) => {
          const access = await api.request<{ url: string }>(
            `/sessions/${sessionId}/assets/${assetId}/access`,
            {
              ...scoped,
              method: "POST",
              body: JSON.stringify({ ttl_seconds: 300 }),
            },
          );
          setAssetUrls((current) => ({ ...current, [assetId]: access.url }));
        }}
      />
    </main>
  );
}

export function ReadyActions({
  api,
  organizationId,
  sessionId,
  revisionId,
  profiles,
  activeIteration,
  onIteration,
}: {
  api: ApiClient;
  organizationId: string;
  sessionId: string;
  revisionId: string;
  profiles: UiCatalog["generation_profiles"];
  activeIteration: VisualizationIteration | null;
  onIteration: (iteration: VisualizationIteration) => void;
}) {
  const [prompt, setPrompt] = useState<PromptRevision | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submissionInFlight = useRef(false);
  const activeStatus = activeIteration?.status === "pending" ? "pending" : null;
  const submitGeneration = async () => {
    if (!prompt || submissionInFlight.current || activeStatus) return;
    submissionInFlight.current = true;
    setIsSubmitting(true);
    try {
      const iteration = await api.request<VisualizationIteration>(
        `/sessions/${sessionId}/visualization-iterations`,
        {
          organizationId,
          method: "POST",
          body: JSON.stringify({
            prompt_revision_id: prompt.prompt_revision_id,
          }),
        },
      );
      onIteration(iteration);
    } finally {
      submissionInFlight.current = false;
      setIsSubmitting(false);
    }
  };
  return (
    <div className="ready-actions">
      {!prompt ? (
        <button
          onClick={() =>
            void api
              .request<PromptRevision>(
                `/sessions/${sessionId}/prompt-revisions`,
                {
                  organizationId,
                  method: "POST",
                  body: JSON.stringify({ expected_revision_id: revisionId }),
                },
              )
              .then(setPrompt)
          }
        >
          Create generation prompt
        </button>
      ) : (
        <>
          <button
            disabled={!profiles.length || isSubmitting || Boolean(activeStatus)}
            onClick={() => void submitGeneration()}
          >
            {isSubmitting ? "Queueing providers…" : "Generate provider results"}
          </button>
          {activeStatus && (
            <p className="notice">
              Visualization iteration: {activeStatus.toUpperCase()}
            </p>
          )}
          {!profiles.length && <p>No generation profiles are configured.</p>}
        </>
      )}
    </div>
  );
}

export function VisualizationIterationPanel({
  api,
  organizationId,
  sessionId,
  locale,
  iterations,
  urls,
  onView,
  onChanged,
}: {
  api: ApiClient;
  organizationId: string;
  sessionId: string;
  locale: string;
  iterations: VisualizationIteration[];
  urls: Record<string, string>;
  onView: (assetId: string) => Promise<void>;
  onChanged: () => Promise<unknown>;
}) {
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const decide = async (
    iterationId: string,
    decision:
      { decision: "select"; asset_id: string } | { decision: "reject_all" },
  ) => {
    setDecisionError(null);
    try {
      await api.request(
        `/sessions/${sessionId}/visualization-iterations/${iterationId}/decision`,
        {
          organizationId,
          method: "POST",
          body: JSON.stringify(decision),
        },
      );
      await onChanged();
    } catch (caught) {
      setDecisionError(
        caught instanceof ApiError
          ? caught.message
          : locale === "ru"
            ? "Не удалось сохранить выбор."
            : "The selection could not be saved.",
      );
    }
  };
  return (
    <section className="panel assets">
      <p className="eyebrow">
        {locale === "ru" ? "Варианты визуализации" : "Visualization results"}
      </p>
      <h2>{locale === "ru" ? "Выберите результат" : "Choose a result"}</h2>
      {decisionError && <div className="alert">{decisionError}</div>}
      {[...iterations].reverse().map((iteration) => (
        <article className="iteration" key={iteration.iteration_id}>
          <div className="list-row">
            <strong>{humanize(iteration.status)}</strong>
            <small>{iteration.runs.length} provider run(s)</small>
          </div>
          {iteration.status === "failed" && (
            <p className="notice">
              {locale === "ru"
                ? "Все поставщики не смогли создать результат."
                : "All providers failed to create a result."}
            </p>
          )}
          <div className="asset-grid">
            {iteration.results.map((result) => {
              const selected =
                iteration.selection?.asset_id === result.asset.asset_id;
              return (
                <article className="asset-card" key={result.asset.asset_id}>
                  {urls[result.asset.asset_id] && (
                    <img
                      src={urls[result.asset.asset_id]}
                      alt={`${result.provider} jewelry result`}
                      referrerPolicy="no-referrer"
                    />
                  )}
                  <span className="badge">{result.provider}</span>
                  {selected && <strong>Current visual</strong>}
                  <button onClick={() => void onView(result.asset.asset_id)}>
                    {locale === "ru" ? "Показать" : "View"}
                  </button>
                  <button
                    disabled={
                      iteration.status === "pending" ||
                      Boolean(iteration.selection)
                    }
                    onClick={() =>
                      void decide(iteration.iteration_id, {
                        decision: "select",
                        asset_id: result.asset.asset_id,
                      })
                    }
                  >
                    {locale === "ru" ? "Выбрать" : "Select"}
                  </button>
                </article>
              );
            })}
          </div>
          {iteration.results.length > 0 && (
            <button
              className="quiet"
              disabled={
                iteration.status === "pending" || Boolean(iteration.selection)
              }
              onClick={() =>
                void decide(iteration.iteration_id, { decision: "reject_all" })
              }
            >
              {locale === "ru" ? "Отклонить все" : "Reject all"}
            </button>
          )}
          {iteration.selection?.decision === "rejected" && (
            <p className="notice">
              {locale === "ru"
                ? "Все результаты отклонены."
                : "All results rejected."}
            </p>
          )}
        </article>
      ))}
      {!iterations.length && (
        <p>{locale === "ru" ? "Результатов пока нет." : "No results yet."}</p>
      )}
    </section>
  );
}

function AssetPanel({
  assets,
  urls,
  onUpload,
  onView,
}: {
  assets: Asset[];
  urls: Record<string, string>;
  onUpload: (file: File) => Promise<void>;
  onView: (assetId: string) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  return (
    <section className="panel assets">
      <h2>Private assets</h2>
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (file) void onUpload(file).then(() => setFile(null));
        }}
      >
        <label>
          Add reference image
          <input
            accept="image/png,image/jpeg,image/webp"
            type="file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button disabled={!file} type="submit">
          Upload reference
        </button>
      </form>
      {(["reference", "generated"] as const).map((kind) => (
        <div key={kind}>
          <h3>{humanize(kind)}</h3>
          <div className="asset-grid">
            {assets
              .filter((asset) => asset.kind === kind)
              .map((asset) => (
                <article className="asset-card" key={asset.asset_id}>
                  {urls[asset.asset_id] && (
                    <img
                      src={urls[asset.asset_id]}
                      alt={`${kind} jewelry asset`}
                      referrerPolicy="no-referrer"
                    />
                  )}
                  <span className="badge">{asset.status}</span>
                  <small>{Math.ceil(asset.byte_size / 1024)} KB</small>
                  <button
                    disabled={asset.status !== "ready"}
                    onClick={() => void onView(asset.asset_id)}
                  >
                    View for 5 minutes
                  </button>
                </article>
              ))}
          </div>
        </div>
      ))}
    </section>
  );
}

function Breadcrumbs({ organizationId }: { organizationId: string }) {
  const client = useQueryClient();
  return (
    <nav aria-label="Breadcrumb">
      <Link
        to="/"
        onClick={() => {
          clearOrganizationQueries(client, organizationId);
        }}
      >
        Organizations
      </Link>
      <span> / </span>
      <Link to={`/organizations/${organizationId}`}>Projects</Link>
    </nav>
  );
}

function submitName(event: FormEvent, submit: () => void): void {
  event.preventDefault();
  submit();
}

function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}

function stateValue(value: unknown): string {
  if (typeof value !== "object" || value === null) return "Not provided";
  const state = value as Record<string, unknown>;
  if (state.availability === "not_applicable") return "Not applicable";
  if (state.availability !== "value") return "Not provided";
  return typeof state.value === "string"
    ? humanize(state.value)
    : JSON.stringify(state.value);
}

export function App() {
  return (
    <ApiProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/auth/callback" element={<Callback />} />
        <Route element={<Protected />}>
          <Route element={<Shell />}>
            <Route index element={<Dashboard />} />
            <Route
              path="organizations/:organizationId"
              element={<OrganizationProjects />}
            />
            <Route
              path="organizations/:organizationId/projects/:projectId"
              element={<ProjectSessions />}
            />
            <Route
              path="organizations/:organizationId/sessions/:sessionId"
              element={<Workspace />}
            />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ApiProvider>
  );
}

export const appQueryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 15_000 } },
});
