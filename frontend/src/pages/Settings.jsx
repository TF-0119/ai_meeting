import Card from "../components/Card";
import Button from "../components/Button";

// 設定ページの簡易プレースホルダー。
export default function Settings() {
  return (
    <section aria-labelledby="settings-title">
      <Card as="article" title="設定" headingLevel="h1" id="settings">
        <p className="muted">
          環境設定やバックエンド切り替えに関するオプションをここに追加できます。
        </p>
        <div className="ui-actions">
          <Button variant="secondary">設定を編集</Button>
          <Button variant="ghost">ドキュメントを見る</Button>
        </div>
      </Card>
    </section>
  );
}
