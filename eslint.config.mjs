import javascript from "@eslint/js";
import typescript from "@typescript-eslint/eslint-plugin";
import react from "eslint-plugin-react";
import globals from "globals";

export default [
  {
    ignores: [
      "**/node_modules/**",
      "dist/**",
      "test/**/*.js",
      "coverage/**",
      "playwright-report/**",
      "test-results/**",
      "htmlcov/**",
      "**/.*",
    ],
  },
  javascript.configs.recommended,
  {
    files: ["**/*.{js,jsx,ts,tsx,mjs,cjs}"],
    ...react.configs.flat.recommended,
    languageOptions: {
      ...react.configs.flat.recommended.languageOptions,
      globals: globals.node,
    },
    settings: { react: { version: "detect" } },
    rules: {
      ...react.configs.flat.recommended.rules,
      "no-empty-function": "off",
      "react/prop-types": "off",
    },
  },
  ...typescript.configs["flat/recommended"].map((config) => ({
    ...config,
    files: config.files ?? ["**/*.{js,jsx,ts,tsx,mjs,cjs}"],
  })),
  {
    files: ["**/*.{js,jsx,ts,tsx,mjs,cjs}"],
    rules: {
      "@typescript-eslint/adjacent-overload-signatures": "error",
      "@typescript-eslint/explicit-module-boundary-types": "warn",
      "@typescript-eslint/no-inferrable-types": "error",
      "@typescript-eslint/no-non-null-assertion": "warn",
      "@typescript-eslint/no-restricted-types": [
        "error",
        { types: { Object: "Use the object type instead." } },
      ],
      "no-extra-semi": "error",
      "@typescript-eslint/no-empty-function": [
        "error",
        { allow: ["private-constructors"] },
      ],
    },
  },
];
