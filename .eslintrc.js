module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  plugins: ["@typescript-eslint"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react/recommended",
  ],
  env: {
    node: true,
  },
  rules: {
    "no-empty-function": "off",
    "@typescript-eslint/no-empty-function": [
      "error",
      {
        allow: ["private-constructors"],
      },
    ],
    "react/prop-types": "off",
  },
  settings: {
    react: {
      version: "detect",
    },
  },
};
