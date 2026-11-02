// Week 6 Step 5: lint with Next's recommended rules (core web vitals + TypeScript).
import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  // Tests stub fetch and browser APIs; loose types there are deliberate.
  { files: ["tests/**"], rules: { "@typescript-eslint/no-explicit-any": "off" } },
];

export default config;
