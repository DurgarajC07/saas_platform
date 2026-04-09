export default {
  '*.{ts,tsx}': ['eslint --fix --max-warnings 0', 'prettier --write'],
  '*.{js,mjs,cjs}': ['prettier --write'],
  '*.{css,md,json}': ['prettier --write'],
}
