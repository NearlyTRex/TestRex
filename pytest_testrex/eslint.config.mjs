// The flat config TestRex lints JavaScript with when a repository has none:
// eslint's recommended rules, written out so the file needs no packages, with
// node and ES2022 globals. .js and .mjs files are modules, .cjs CommonJS.

const RECOMMENDED = [
    "constructor-super", "for-direction", "getter-return", "no-async-promise-executor", "no-case-declarations",
    "no-class-assign", "no-compare-neg-zero", "no-cond-assign", "no-const-assign", "no-constant-binary-expression",
    "no-constant-condition", "no-control-regex", "no-debugger", "no-delete-var", "no-dupe-args",
    "no-dupe-class-members", "no-dupe-else-if", "no-dupe-keys", "no-duplicate-case", "no-empty",
    "no-empty-character-class", "no-empty-pattern", "no-empty-static-block", "no-ex-assign",
    "no-extra-boolean-cast", "no-fallthrough", "no-func-assign", "no-global-assign", "no-import-assign",
    "no-invalid-regexp", "no-irregular-whitespace", "no-loss-of-precision", "no-misleading-character-class",
    "no-new-native-nonconstructor", "no-nonoctal-decimal-escape", "no-obj-calls", "no-octal",
    "no-prototype-builtins", "no-redeclare", "no-regex-spaces", "no-self-assign", "no-setter-return",
    "no-shadow-restricted-names", "no-sparse-arrays", "no-this-before-super", "no-undef",
    "no-unexpected-multiline", "no-unreachable", "no-unsafe-finally", "no-unsafe-negation",
    "no-unsafe-optional-chaining", "no-unused-labels", "no-unused-private-class-members", "no-unused-vars",
    "no-useless-backreference", "no-useless-catch", "no-useless-escape", "no-with", "require-yield", "use-isnan",
    "valid-typeof",
];

const NODE_GLOBALS = [
    "AbortController", "AbortSignal", "Blob", "BroadcastChannel", "Buffer", "Event", "EventTarget", "FormData",
    "Headers", "MessageChannel", "MessagePort", "Request", "Response", "TextDecoder", "TextEncoder", "URL",
    "URLSearchParams", "__dirname", "__filename", "atob", "btoa", "clearImmediate", "clearInterval",
    "clearTimeout", "console", "crypto", "exports", "fetch", "global", "module", "performance", "process",
    "queueMicrotask", "require", "setImmediate", "setInterval", "setTimeout", "structuredClone",
];

const rules = Object.fromEntries(RECOMMENDED.map((rule) => [rule, "error"]));
const globals = Object.fromEntries(NODE_GLOBALS.map((name) => [name, "readonly"]));

export default [
    {
        files: ["**/*.js", "**/*.mjs"],
        languageOptions: {ecmaVersion: 2022, sourceType: "module", globals},
        rules,
    },
    {
        files: ["**/*.cjs"],
        languageOptions: {ecmaVersion: 2022, sourceType: "commonjs", globals},
        rules,
    },
];
