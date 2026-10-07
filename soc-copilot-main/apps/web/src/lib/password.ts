// Shared password policy + strength helpers. Same rules apply to user
// self-registration (login/page.tsx) and admin password resets
// (admin/page.tsx) — keep both flows aligned by importing from here.

export type PasswordRule = {
  id: string;
  label: string;
  test: (pw: string) => boolean;
};

export const PASSWORD_RULES: PasswordRule[] = [
  { id: "len", label: "Al menos 10 caracteres", test: (p) => p.length >= 10 },
  { id: "upper", label: "Incluye mayúscula", test: (p) => /[A-Z]/.test(p) },
  { id: "lower", label: "Incluye minúscula", test: (p) => /[a-z]/.test(p) },
  { id: "digit", label: "Incluye dígito", test: (p) => /\d/.test(p) },
  { id: "symbol", label: "Incluye símbolo", test: (p) => /[^A-Za-z0-9]/.test(p) },
];

// Minimum zxcvbn score required (0-4). 2 == "Aceptable".
export const MIN_STRENGTH_SCORE = 2;

export const STRENGTH_COLORS = [
  "bg-rose-600",
  "bg-rose-500",
  "bg-amber-500",
  "bg-emerald-500",
  "bg-emerald-400",
];

export const STRENGTH_LABELS = [
  "Muy débil",
  "Débil",
  "Aceptable",
  "Fuerte",
  "Excelente",
];

export type ZxcvbnFn = (pw: string) => {
  score: number;
  feedback: { warning?: string; suggestions: string[] };
};

// zxcvbn-ts is heavy (~400KB). Load lazily so it never blocks first paint.
export async function loadZxcvbn(): Promise<ZxcvbnFn> {
  const [core, common, es] = await Promise.all([
    import("@zxcvbn-ts/core"),
    import("@zxcvbn-ts/language-common"),
    import("@zxcvbn-ts/language-es-es"),
  ]);
  core.zxcvbnOptions.setOptions({
    translations: es.translations,
    dictionary: { ...common.dictionary, ...es.dictionary },
    graphs: common.adjacencyGraphs,
  });
  return core.zxcvbn as ZxcvbnFn;
}

export function evaluatePassword(pw: string) {
  const rules = PASSWORD_RULES.map((r) => ({ ...r, ok: r.test(pw) }));
  return {
    rules,
    allRulesPass: rules.every((r) => r.ok),
  };
}
