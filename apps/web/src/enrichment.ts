import { ApiClient } from "./api";
import type { DesignRevision, Session } from "./types";

export type Decision =
  "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN";
export interface Frame {
  revision_id: string;
  enrichment_cycle_id: string;
  enrichment_cycle_number: number;
  enrichment_result_hash: string;
  plan_id: string;
  plan_hash: string;
  history_root_sha256: string;
  revision_sha256: string;
}
export interface NativeQuestion {
  clarification_id: string;
  text: string;
  category: string;
  cause_id?: string;
  allowed_decisions?: Decision[];
  options: { value: string; label: string; option_id?: string }[];
}
export type Question =
  | {
      question_kind: "NATIVE";
      retained_base: "L" | "F";
      native_question: NativeQuestion;
    }
  | {
      question_kind: "KEEP_RELEASE";
      offer: {
        offer_id: string;
        intent_id: string;
        rendered_question: string;
        requested_value_sha256: string;
        allowed_decisions: ("ACCEPT" | "REJECT")[];
      };
    };
export interface EnrichmentState {
  schema_version: "3.0.0";
  retained_base: "L" | "F";
  extension_profile: string | null;
  continuation_enabled: boolean;
  current_frame: Frame;
  questions: Question[];
  status: string;
  description: { text: string };
  protection_projection: {
    roots: { source_wording: string; [key: string]: unknown }[];
    pending_requests: {
      intent_id: string;
      status: string;
      [key: string]: unknown;
    }[];
  };
  native_frontier: null | {
    frontier_core: {
      cause_states: {
        cause_id: string;
        status: string;
        offer_state: string;
        availability_target_ref: { concrete_target: string };
      }[];
    };
  };
}
export interface Conversation {
  schema_version: "1.0.0";
  session_id: string;
  revision: Omit<DesignRevision, "schema_version"> & {
    schema_version: "1.0.0" | "1.1.0";
  };
  state: EnrichmentState | null;
  events: {
    event_id: string;
    kind: "user" | "question" | "decision";
    created_at: string;
    text: string;
    outcome: string | null;
    message_id: string | null;
  }[];
}
export interface FinalOutput {
  description: { text: string };
  internal_final_prompt: {
    prompt_text: string;
    readiness: string;
    [key: string]: unknown;
  };
}

export interface CompletionContext {
  schema_version: "completion-context/1.0.0";
  status: "AWAITING_COMPLETION";
  expected_frame: Frame;
  question: {
    question_id: string;
    text: string;
    choices: ("YES" | "NO")[];
  };
}
export interface CompletionPromptV6 {
  schema_version: "6.0.0";
  prompt_text: string;
  readiness: "READY" | "READY_WITH_UNRESOLVED";
  policy_sha256: string;
  effective_parameters: { concrete_target: string; value: unknown }[];
  parameter_sources: Record<string, Record<string, unknown>>;
  assumptions: {
    target_path: string;
    proposed_value: unknown;
    rule_id: string;
    rule_version: string;
    rationale: string;
  }[];
  omitted_targets: string[];
}
export interface CompletionResult {
  schema_version: "1.0.0";
  completion_id: string;
  status: "FINAL" | "EDITING";
  is_current: boolean;
  replayed: boolean;
  expected_frame: Frame;
  final_prompt: CompletionPromptV6 | null;
  content_hash: string;
  question: CompletionContext["question"];
}
export type CompletionView = CompletionContext | CompletionResult;

/** Wire existing server commands; never interpret text or compute authority/hash evidence. */
export class EnrichmentClient {
  readonly path: string;
  constructor(
    readonly api: ApiClient,
    readonly organizationId: string,
    readonly sessionId: string,
  ) {
    this.path = `/v1/sessions/${sessionId}/prompt-enrichment`;
  }
  read() {
    return this.api.request<Conversation>(`${this.path}/conversation`, {
      organizationId: this.organizationId,
    });
  }
  message(content: string) {
    return this.api.request<{ message_id: string }>(
      `/sessions/${this.sessionId}/messages`,
      {
        organizationId: this.organizationId,
        method: "POST",
        body: JSON.stringify({ content }),
      },
    );
  }
  post(route: string, body: object) {
    return this.api.request<unknown>(`${this.path}/${route}`, {
      organizationId: this.organizationId,
      method: "POST",
      body: JSON.stringify(body),
    });
  }
  async send(session: Session, snapshot: Conversation, content: string) {
    const message = await this.message(content);
    const s = snapshot.state;
    if (!s)
      return this.post("initial", {
        ...(session.artifacts.questions === "2.0.0"
          ? { schema_version: "2.0.0" }
          : {}),
        expected_revision_id: snapshot.revision.revision_id,
        message_id: message.message_id,
      });
    return this.post("corrections", {
      ...this.nativeFrame(s),
      message_id: message.message_id,
    });
  }
  private nativeFrame(s: EnrichmentState) {
    const f = s.current_frame;
    if (s.extension_profile)
      return {
        schema_version: "3.0.0",
        request_id: crypto.randomUUID(),
        expected_head: f,
      };
    return {
      ...(s.retained_base === "F"
        ? {
            schema_version: "2.0.0",
            expected_enrichment_cycle_id: f.enrichment_cycle_id,
            expected_enrichment_result_hash: f.enrichment_result_hash,
            expected_clarification_plan_hash: f.plan_hash,
          }
        : {}),
      expected_revision_id: f.revision_id,
    };
  }
  async answer(
    s: EnrichmentState,
    q: Question,
    decision: Decision,
    option?: NativeQuestion["options"][number],
  ) {
    const wording =
      q.question_kind === "KEEP_RELEASE"
        ? q.offer.rendered_question
        : q.native_question.text;
    // Persist the explicit human action as its Message provenance; it is not a text parse.
    const message = await this.message(
      `${wording}\n${option?.label ?? decision}`,
    );
    const f = s.current_frame;
    if (q.question_kind === "KEEP_RELEASE")
      return this.post("clarification-answers", {
        schema_version: "3.0.0",
        answer_kind: "KEEP_RELEASE",
        answer_id: crypto.randomUUID(),
        message_id: message.message_id,
        expected_head: f,
        clarification_plan_id: f.plan_id,
        clarification_id: q.offer.offer_id,
        intent_id: q.offer.intent_id,
        requested_value_sha256: q.offer.requested_value_sha256,
        decision,
      });
    const common = {
      answer_id: crypto.randomUUID(),
      message_id: message.message_id,
      clarification_plan_id: f.plan_id,
      clarification_id: q.native_question.clarification_id,
    };
    const native = {
      retained_base: s.retained_base,
      decision,
      selected_option: option?.value ?? null,
      ...(s.retained_base === "F"
        ? { selected_option_id: option?.option_id ?? null }
        : {}),
    };
    if (s.extension_profile)
      return this.post("clarification-answers", {
        ...common,
        schema_version: "3.0.0",
        answer_kind: "NATIVE",
        expected_head: f,
        native,
      });
    return this.post("clarification-answers", {
      ...common,
      decision,
      selected_option: option?.value ?? null,
      expected_revision_id: f.revision_id,
      ...(s.retained_base === "F"
        ? {
            schema_version: "2.0.0",
            plan_content_hash: f.plan_hash,
            selected_option_id: option?.option_id ?? null,
          }
        : {}),
    });
  }
  async admit(s: EnrichmentState) {
    const message = await this.message(
      "Continue this design using protected continuation.",
    );
    return this.post("continuation-admissions", {
      schema_version: "1.0.0",
      request_id: crypto.randomUUID(),
      message_id: message.message_id,
      expected_head: s.current_frame,
    });
  }
  async resume(s: EnrichmentState, id: string, keep = false) {
    const message = await this.message("Resume this clarification explicitly.");
    const frame = this.nativeFrame(s);
    return this.post(
      `clarifications/${id}/resume`,
      s.extension_profile
        ? {
            ...frame,
            schema_version: "3.0.0",
            request_id: crypto.randomUUID(),
            message_id: message.message_id,
            ...(keep
              ? { resume_kind: "KEEP_RELEASE", intent_id: id }
              : { resume_kind: "NATIVE", retained_base: "F", cause_id: id }),
          }
        : {
            ...frame,
            schema_version: "1.0.0",
            request_id: crypto.randomUUID(),
            message_id: message.message_id,
          },
    );
  }
  currentCompletion() {
    return this.api.request<CompletionView>(
      `${this.path}/completions/current`,
      {
        organizationId: this.organizationId,
      },
    );
  }
  // Keep a submitted command stable across a transport retry; do not create a
  // fresh completion Message when POST reached the server but its response was lost.
  private pendingCompletion: {
    frame: string;
    choice: "YES" | "NO";
    body: {
      schema_version: "1.0.0";
      request_id: string;
      message_id: string;
      expected_frame: Frame;
      anything_else: "YES" | "NO";
    };
  } | null = null;
  async complete(s: EnrichmentState, choice: "YES" | "NO") {
    const frame = JSON.stringify(s.current_frame);
    if (
      !this.pendingCompletion ||
      this.pendingCompletion.frame !== frame ||
      this.pendingCompletion.choice !== choice
    ) {
      const message = await this.message(choice);
      this.pendingCompletion = {
        frame,
        choice,
        body: {
          schema_version: "1.0.0",
          request_id: crypto.randomUUID(),
          message_id: message.message_id,
          expected_frame: s.current_frame,
          anything_else: choice,
        },
      };
    }
    const result = await this.api.request<CompletionResult>(
      `${this.path}/completions`,
      {
        organizationId: this.organizationId,
        method: "POST",
        body: JSON.stringify(this.pendingCompletion.body),
      },
    );
    this.pendingCompletion = null;
    return result;
  }
  final(s: EnrichmentState) {
    return this.api.request<FinalOutput>(
      `${this.path}/final-output?output_version=4.0.0${s.retained_base === "L" ? "&projection=jewelai.legacy-l.compat/1.0.0" : ""}`,
      {
        organizationId: this.organizationId,
        headers: { "If-Match": s.current_frame.history_root_sha256 },
      },
    );
  }
}

// Present only command choices supported by the existing native wire contract.
export function decisions(q: NativeQuestion): Decision[] {
  if (q.allowed_decisions) return q.allowed_decisions;
  return [
    ...(q.options.length ? ["SELECT_OPTION" as const] : []),
    ...(["preference_acceptance", "knowledge_recommendation"].includes(
      q.category,
    )
      ? [
          ...(q.options.length === 1 ? ["ACCEPT" as const] : []),
          "REJECT" as const,
        ]
      : []),
    "SKIP",
    "UNKNOWN",
  ];
}
