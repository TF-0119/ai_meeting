import { forwardRef } from "react";
import { classNames } from "../utils/classNames";

const VARIANT_CLASS = {
  primary: "ui-button ui-button--primary",
  secondary: "ui-button ui-button--secondary",
  ghost: "ui-button ui-button--ghost",
  danger: "ui-button ui-button--danger",
};

const DEFAULT_TAG = "button";

const Button = forwardRef(function Button(
  {
    as: Component = DEFAULT_TAG,
    variant = "primary",
    className = "",
    isLoading = false,
    leadingIcon,
    trailingIcon,
    children,
    ...props
  },
  ref,
) {
  const variantClass = VARIANT_CLASS[variant] ?? VARIANT_CLASS.primary;
  const mergedClassName = classNames(variantClass, className);
  const content = (
    <>
      {leadingIcon ? <span className="ui-button__icon" aria-hidden>{leadingIcon}</span> : null}
      <span>{children}</span>
      {trailingIcon ? <span className="ui-button__icon" aria-hidden>{trailingIcon}</span> : null}
    </>
  );

  const componentProps = {
    ref,
    className: mergedClassName,
    "data-variant": variant,
    "aria-busy": isLoading || undefined,
    ...props,
  };

  if (Component === "button" && componentProps.type === undefined) {
    componentProps.type = "button";
  }

  return <Component {...componentProps}>{content}</Component>;
});

export default Button;
