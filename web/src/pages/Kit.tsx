import { useState } from "react";
import { Badge, Button, Card, Field, Input, PageHeader } from "../ui";
import { Chip, Donut, EmptyState, Logo, PillTabs, ProgressBar, RailCard, SectionHeader, Skeleton, StatTile } from "../components/kit";
import { PageBody } from "../app/Shell";

const sw = [
  ["bg", "#07070c"], ["surface", "#101017"], ["surface-2", "#16161f"], ["line", "#23232f"],
  ["muted", "#a1a1b8"], ["lime", "#d7ff3f"], ["pink", "#ff2d95"], ["violet", "#a855f7"],
];

/** Kitchen sink: every design-system piece on one page (#/kit). */
export default function Kit() {
  const [tab, setTab] = useState("a"); const [chip, setChip] = useState(true);
  return (
    <div className="animate-fade-up space-y-5">
      <PageHeader title="Design" accent="kit" sub="Every token and component the rest of the app is built from." />

      <PageBody rail={<>
        <RailCard title="Shape &amp; spacing">
          <dl className="kv">
            <dt>--r-md</dt><dd>0.75rem</dd>
            <dt>--r-lg</dt><dd>1rem</dd>
            <dt>--r-xl</dt><dd>1.25rem</dd>
            <dt>Sidebar</dt><dd>15.5rem</dd>
            <dt>Rail</dt><dd>21rem</dd>
          </dl>
        </RailCard>
        <RailCard title="Gradients">
          <ul className="space-y-2 text-xs">
            <li className="flex items-center gap-2"><i className="h-4 w-10 rounded bg-gradient-to-r from-pink to-violet" />brand gradient</li>
            <li className="flex items-center gap-2"><i className="h-4 w-10 rounded bg-gradient-to-r from-pink to-brand" />progress gradient</li>
            <li className="flex items-center gap-2"><i className="h-4 w-10 rounded bg-gradient-to-br from-pink/30 to-violet/10" />page glow</li>
          </ul>
        </RailCard>
      </>}>
        <div className="space-y-4">
          <Card title="Colours"><div className="flex flex-wrap gap-3">{sw.map(([n, c]) => (
            <div key={n} className="text-center text-xs"><div className="h-12 w-20 rounded-xl border border-slate-800" style={{ background: c }} />{n}<div className="text-slate-400">{c}</div></div>
          ))}</div></Card>

          <Card title="Type">
            <div className="display text-5xl md:text-6xl">Turn ideas into <span className="grad-text">AI videos</span></div>
            <h2 className="page-title mt-5">Page title with a <span className="grad-text">gradient accent</span></h2>
            <p className="mt-3 text-slate-300">Body text in Inter. <span className="text-slate-400">Muted text.</span> <span className="text-brand">Lime link.</span></p>
          </Card>

          <Card title="Buttons">
            <div className="flex flex-wrap items-center gap-2">
              <Button>Primary</Button><Button variant="pink">Pink</Button><Button variant="outline">Outline</Button>
              <Button variant="ghost">Ghost</Button><Button variant="danger">Danger</Button><Button variant="soft">Soft</Button><Button disabled>Disabled</Button>
              <Button size="sm">Small</Button><Button size="lg">Large</Button>
            </div>
          </Card>

          <Card title="Badges and chips">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="green">green</Badge><Badge tone="amber">amber</Badge><Badge tone="red">red</Badge>
              <Badge tone="pink">Real Mode</Badge><Badge tone="lime">Approved</Badge><Badge tone="sky">sky</Badge><Badge>slate</Badge>
              <Chip active={chip} onClick={() => setChip(!chip)}>Tamil</Chip>
              <Chip active={!chip} onClick={() => setChip(!chip)} tone="pink">English</Chip>
            </div>
          </Card>

          <Card title="Pill tabs">
            <PillTabs value={tab} onChange={setTab} items={[{ id: "a", label: "Characters", count: 2 }, { id: "b", label: "Backgrounds", count: 8 }, { id: "c", label: "Scene Frames", count: 12 }, { id: "d", label: "Uploads", count: 2 }]} />
          </Card>

          <Card title="Progress, donut, stats">
            <div className="flex flex-wrap items-center gap-6">
              <div className="w-64"><ProgressBar value={93} label="Budget used" /></div>
              <Donut value={5.29} max={5.67} />
              <div className="grid w-72 grid-cols-3 gap-2">
                <StatTile value="$3.62" label="Used" /><StatTile value="$1.67" label="Discarded" tone="text-amber-400" /><StatTile value="$5.29" label="Total" />
              </div>
            </div>
          </Card>

          <Card title="Inputs">
            <div className="grid gap-3 md:grid-cols-2">
              <Input placeholder="Text input" /><Field rows={2} placeholder="Textarea" />
            </div>
          </Card>

          <Card title="Logo">
            <div className="flex flex-wrap items-center gap-8"><Logo /><Logo compact /></div>
          </Card>

          <SectionHeader title="Section header" sub="With a count and an action on the right" count={12} right={<Button variant="outline" size="sm">Action</Button>} />
          <div className="grid gap-3 md:grid-cols-2">
            <EmptyState title="Nothing here yet" text="Empty states say what to do next." action={<Button size="sm">Do it</Button>} />
            <div className="space-y-2"><Skeleton className="h-8" /><Skeleton className="h-8 w-2/3" /></div>
          </div>
        </div>
      </PageBody>
    </div>
  );
}
