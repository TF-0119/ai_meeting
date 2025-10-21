import { useId } from "react";
import { classNames } from "../utils/classNames";

export default function Card({
  as: Component = "section",
  title,
  headingLevel = "h2",
  description,
  children,
  className = "",
  actions,
  id,
  ...props
}) {
  const generatedId = useId();
  const headingId = title ? `${id ?? generatedId}-title` : undefined;
  const descriptionId = description ? `${id ?? generatedId}-description` : undefined;
  const labelledBy = headingId;
  const describedBy = descriptionId;
  const HeadingTag = headingLevel;

  return (
    <Component
      className={classNames("ui-card", className)}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      {...props}
    >
      {(title || description) && (
        <header className="ui-card__header">
          {title ? (
            <HeadingTag id={headingId} className="ui-card__title">
              {title}
            </HeadingTag>
          ) : null}
          {description ? (
            <p id={descriptionId} className="ui-card__description">
              {description}
            </p>
          ) : null}
        </header>
      )}
      <div className="ui-card__content">{children}</div>
      {actions ? <div className="ui-card__actions">{actions}</div> : null}
    </Component>
  );
}
