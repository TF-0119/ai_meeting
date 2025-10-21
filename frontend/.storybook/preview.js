import { INITIAL_VIEWPORTS } from "@storybook/addon-viewport";
import { applyTheme, THEMES_AVAILABLE } from "../src/theme";
import "../src/styles/index.css";

export const parameters = {
  controls: { expanded: true },
  viewport: {
    viewports: INITIAL_VIEWPORTS,
  },
  backgrounds: {
    default: "app",
    values: [
      { name: "app", value: "var(--color-surface-app)" },
      { name: "card", value: "var(--color-surface-layer)" },
      { name: "contrast", value: "#121318" },
    ],
  },
  a11y: {
    element: "#storybook-root",
    config: {
      rules: [
        { id: "color-contrast", enabled: true },
      ],
    },
  },
};

export const globalTypes = {
  theme: {
    name: "テーマ",
    description: "ライト/ダークモードを切り替えます",
    defaultValue: "light",
    toolbar: {
      icon: "circlehollow",
      items: THEMES_AVAILABLE.map((value) => ({ value, title: value })),
    },
  },
};

export const decorators = [
  (Story, context) => {
    applyTheme(context.globals.theme);
    return Story();
  },
];
