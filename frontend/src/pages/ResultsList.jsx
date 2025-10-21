import Card from "../components/Card";

// 会議結果一覧の簡易プレースホルダー。
export default function ResultsList() {
  return (
    <section aria-labelledby="results-title">
      <Card as="article" title="結果一覧" headingLevel="h1" id="results">
        <p className="muted">
          過去の会議結果を表示するページです。今後の実装でログ一覧などを表示できます。
        </p>
      </Card>
    </section>
  );
}
