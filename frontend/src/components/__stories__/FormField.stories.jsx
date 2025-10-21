import { useState } from "react";
import FormField from "../FormField";

export default {
  title: "Components/FormField",
  component: FormField,
};

export function TextFieldExample() {
  const [value, setValue] = useState("");
  return (
    <FormField
      id="example"
      label="会議テーマ"
      hint="AI が理解しやすいように具体的に記述してください。"
      error={value.trim() ? "" : "テーマを入力してください。"}
      required
    >
      <input
        className="ui-input"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="例: 週次の進捗確認"
      />
    </FormField>
  );
}

export function SelectFieldExample() {
  const [backend, setBackend] = useState("ollama");
  return (
    <FormField id="backend" label="バックエンド" hint="利用するサービスを選択します。">
      <select className="ui-select" value={backend} onChange={(event) => setBackend(event.target.value)}>
        <option value="ollama">Ollama (ローカル)</option>
        <option value="openai">OpenAI API</option>
      </select>
    </FormField>
  );
}
