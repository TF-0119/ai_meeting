import Button from "../Button";

export default {
  title: "Components/Button",
  component: Button,
  parameters: {
    a11y: {
      config: {
        rules: [{ id: "color-contrast", enabled: true }],
      },
    },
  },
  args: {
    children: "アクション",
  },
  argTypes: {
    variant: {
      control: { type: "radio" },
      options: ["primary", "secondary", "ghost", "danger"],
    },
    isLoading: {
      control: "boolean",
    },
  },
};

export const Primary = {
  args: {
    variant: "primary",
  },
};

export const Secondary = {
  args: {
    variant: "secondary",
  },
};

export const Ghost = {
  args: {
    variant: "ghost",
  },
};

export const Danger = {
  args: {
    variant: "danger",
  },
};
