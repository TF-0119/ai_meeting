import Card from "../components/Card";

// 進行中会議一覧の簡易プレースホルダー。
export default function Ongoing() {
  return (
    <section aria-labelledby="ongoing-title">
      <Card as="article" title="進行中の会議" headingLevel="h1" id="ongoing">
        <p className="muted">
          現在進行中の会議はありません。会議が開始されるとここに表示されます。
        </p>
      </Card>
    </section>
  );
}
