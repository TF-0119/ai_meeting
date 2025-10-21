import { cloneElement, useId } from "react";
import FieldError from "./FieldError";
import { classNames } from "../utils/classNames";

export default function FormField({
  id,
  label,
  labelTag: LabelTag = "label",
  hint,
  error,
  required = false,
  children,
  layout = "column",
  description,
  className = "",
}) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  const hintId = hint ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const descriptionId = description ? `${controlId}-description` : undefined;
  const describedByIds = [hintId, errorId, descriptionId].filter(Boolean).join(" ") || undefined;

  const controlClassName = classNames(children.props?.className, error && "is-error");
  const control = cloneElement(children, {
    id: controlId,
    "aria-describedby": describedByIds,
    "aria-invalid": Boolean(error) || undefined,
    className: controlClassName,
  });

  return (
    <div
      className={classNames("ui-field", `ui-field--${layout}`, className, error && "is-error")}
    >
      <LabelTag className="ui-field__label" htmlFor={LabelTag === "label" ? controlId : undefined}>
        <span className="ui-field__label-text">
          {label}
          {required ? <span className="ui-field__required">*</span> : null}
        </span>
        {description ? (
          <span id={descriptionId} className="ui-field__description">
            {description}
          </span>
        ) : null}
      </LabelTag>
      <div className="ui-field__control">{control}</div>
      {hint ? (
        <p id={hintId} className="ui-field__hint">
          {hint}
        </p>
      ) : null}
      <FieldError id={errorId} message={error} />
    </div>
  );
}
