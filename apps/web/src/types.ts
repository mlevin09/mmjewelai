export interface Membership {
  organization_id: string;
  organization_name: string;
  role: "owner" | "admin" | "member";
}

export interface Me {
  principal_id: string;
  email: string | null;
  display_name: string | null;
  memberships: Membership[];
}

export interface Organization {
  organization_id: string;
  name: string;
  created_at: string;
}

export interface Project {
  project_id: string;
  organization_id: string;
  name: string;
  created_at: string;
}

export interface Session {
  session_id: string;
  project_id: string;
  role_id: string;
  locale: "en" | "ru";
  created_at: string;
  updated_at: string;
  current_revision_id: string;
  artifacts: Record<string, string>;
}

export interface ValueState<T> {
  availability: "value";
  origin: "explicit" | "derived" | "assumed";
  value: T;
  confirmed: boolean;
  locked: boolean;
  source?: MessageSource;
}

export interface MessageSource {
  kind: "message";
  message_id: string;
  recorded_at: string;
}

export interface DesignRevision {
  schema_version: "1.0.0";
  design_id: string;
  revision_id: string;
  revision: number;
  parent_revision_id: string | null;
  created_at: string;
  event: unknown;
  design: Design;
}

export interface Design {
  jewelry_type: unknown;
  metal: {
    material: unknown;
    color: unknown;
    purity: unknown;
    finish: unknown;
  };
  center_stone: {
    material: unknown;
    shape: unknown;
    cut: unknown;
    weight: unknown;
    dimensions: unknown;
    color: unknown;
    setting: unknown;
    orientation: unknown;
  };
  side_stones: Array<{
    group_id: string;
    stones: unknown;
    quantity: unknown;
  }>;
  construction: unknown;
  style: unknown;
  references: unknown;
  visual_constraints: unknown;
}

export type AnswerContract =
  | {
      kind: "dictionary_id";
      dictionary_category: string;
      schema_type: "DomainId";
    }
  | { kind: "dimensions"; unit: "mm"; components: ["length", "width", "depth"] }
  | {
      kind: "stone_quantity";
      value: "positive_integer";
      scopes: ["per_side", "per_item", "per_pair"];
    };

export interface Evaluation {
  revision_id: string;
  decision: {
    decision: "ask" | "derive" | "assume" | "block" | "ready";
    reason: string;
    target?: string;
    concrete_target?: string;
    question_id?: string;
  };
  rendered_question: null | {
    question_id: string;
    wording: string;
    target: string;
    answer_contract: AnswerContract;
    locale: "en" | "ru";
  };
}

export interface DictionaryOption {
  domain_id: string;
  category: "stone_shape" | "stone_setting" | "metal_color";
  term: string;
}

export interface UiCatalog {
  roles_artifact_version: string;
  roles: Array<{ role_id: string }>;
  locales: Array<"en" | "ru">;
  generation_profiles: Array<{
    profile_id: string;
    profile_version: string;
    output_count: number;
  }>;
}

export interface Asset {
  asset_id: string;
  kind: "reference" | "generated";
  status: "pending" | "ready" | "failed";
  content_type: string;
  byte_size: number;
  generation_run_id: string | null;
  created_at: string;
}

export interface GenerationRun {
  generation_run_id: string;
  prompt_revision_id: string;
  profile_id: string;
  status: "pending" | "running" | "succeeded" | "failed";
  attempt: number;
  parent_generation_run_id: string | null;
  error?: { code: string; detail: string } | null;
}

export interface PromptRevision {
  prompt_revision_id: string;
  specification_revision_id: string;
  compiled_prompt: { prompt_text: string };
  created_at: string;
}
