import React from "react";
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from "remotion";

const FRAMES = [348, 456, 442, 552, 254, 207];
const TOTAL = FRAMES.reduce((sum, value) => sum + value, 0);
const NAVY = "#0B1F3A";
const YELLOW = "#F5C518";
const WHITE = "#FFFFFF";

const fontFace = `
@font-face {
  font-family: "Vazirmatn";
  src: url("${staticFile("Vazirmatn-Regular.ttf")}") format("truetype");
  font-weight: 400;
}
@font-face {
  font-family: "Vazirmatn";
  src: url("${staticFile("Vazirmatn-Bold.ttf")}") format("truetype");
  font-weight: 700;
}
`;

type Still = {
  file: string;
  width: number;
  height: number;
  original: boolean;
};

export type PhotoTicketAssets = {
  train: Still;
  station: Still;
  card: Still;
};

const preview: PhotoTicketAssets = {
  train: {file: "ticket-visual/birkenwerder.jpg", width: 960, height: 1440, original: false},
  station: {file: "ticket-visual/ostkreuz.jpg", width: 960, height: 640, original: false},
  card: {file: "ticket-visual/vbn-card.jpg", width: 960, height: 1370, original: false},
};

const starts = FRAMES.reduce<number[]>((items, _value, index) => {
  const previous = index === 0 ? 0 : items[index - 1] + FRAMES[index - 1];
  items.push(previous);
  return items;
}, []);

const sceneOf = (frame: number) => {
  const found = starts.findIndex((start, index) => frame >= start && frame < start + FRAMES[index]);
  const index = found === -1 ? FRAMES.length - 1 : found;
  return {index, local: frame - starts[index]};
};

export const PhotoTicketReel: React.FC<{assets?: PhotoTicketAssets}> = ({assets = preview}) => {
  const frame = useCurrentFrame();
  const {index, local} = sceneOf(frame);
  const incoming = interpolate(local, [0, 12], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{backgroundColor: NAVY, color: WHITE, fontFamily: "Vazirmatn, sans-serif"}}>
      <style>{fontFace}</style>
      <AbsoluteFill style={{opacity: index === 0 ? 1 : incoming}}>
        <Scene index={index} local={local} assets={assets} />
      </AbsoluteFill>
      <Caption index={index} local={local} />
    </AbsoluteFill>
  );
};

const Scene: React.FC<{index: number; local: number; assets: PhotoTicketAssets}> = ({index, local, assets}) => {
  if (index === 0) return <PriceScene local={local} still={assets.train} />;
  if (index === 1) return <DateScene local={local} still={assets.station} />;
  if (index === 2) return <ProviderScene local={local} still={assets.card} />;
  if (index === 3) return <BahnScene local={local} still={assets.train} />;
  if (index === 4) return <BvgScene local={local} />;
  return <CloseScene local={local} still={assets.card} />;
};

const StillPlate: React.FC<{
  still: Still;
  local: number;
  duration: number;
  focusX: number;
  focusY: number;
  maxHeight: number;
}> = ({still, local, duration, focusX, focusY, maxHeight}) => {
  const cover = Math.max(1080 / still.width, maxHeight / still.height);
  const sharp = still.original && cover <= 1;
  const scale = sharp ? cover * interpolate(local, [0, duration], [1, 1.08], {extrapolateRight: "clamp"}) : Math.min(1.12, 1080 / still.width);
  const width = still.width * scale;
  const height = still.height * scale;
  const drift = sharp ? interpolate(local, [0, duration], [0, 36], {extrapolateRight: "clamp"}) : 0;
  const left = sharp ? (1080 - width) * (focusX / 100) - drift : (1080 - width) / 2 + drift;
  const top = sharp ? (maxHeight - height) * (focusY / 100) : 0;
  return (
    <Img
      src={staticFile(still.file)}
      style={{
        position: "absolute",
        width,
        height,
        left,
        top,
        objectFit: "cover",
      }}
    />
  );
};

const Shade: React.FC<{strong?: boolean}> = ({strong = false}) => (
  <AbsoluteFill
    style={{
      background: strong
        ? "linear-gradient(180deg, rgba(11,31,58,0.55) 0%, rgba(11,31,58,0.15) 32%, rgba(11,31,58,0.82) 68%, #0B1F3A 100%)"
        : "linear-gradient(180deg, rgba(11,31,58,0.2) 0%, rgba(11,31,58,0.55) 58%, #0B1F3A 100%)",
    }}
  />
);

const Copy: React.FC<{top: number; children: React.ReactNode}> = ({top, children}) => (
  <div style={{position: "absolute", top, left: 72, right: 168, direction: "rtl", textAlign: "right"}}>{children}</div>
);

const Credit: React.FC<{text: string; top: number}> = ({text, top}) => (
  <div style={{position: "absolute", top, left: 72, right: 168, direction: "ltr", textAlign: "left", fontSize: 24, lineHeight: 1.3, color: "rgba(255,255,255,0.86)"}}>
    {text}
  </div>
);

const Euro: React.FC<{amount: string; size: number; color?: string}> = ({amount, size, color = WHITE}) => (
  <div style={{direction: "ltr", unicodeBidi: "isolate", textAlign: "right", fontSize: size, fontWeight: 700, lineHeight: 1.05, color}}>
    {amount}
  </div>
);

const PriceScene: React.FC<{local: number; still: Still}> = ({local, still}) => {
  const grow = interpolate(local, [18, 90], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const shown = (63 + grow * 3.8).toFixed(2);
  return (
    <AbsoluteFill>
      <StillPlate still={still} local={local} duration={FRAMES[0]} focusX={46} focusY={18} maxHeight={1920} />
      <Shade strong />
      <Copy top={250}>
        <div style={{fontSize: 36, color: YELLOW}}>قطار منطقه‌ای · بیرکنوردر · ۲۰۱۶</div>
        <div style={{marginTop: 18, fontSize: 64, fontWeight: 700, lineHeight: 1.25}}>از اول ژانویه ۲۰۲۷</div>
        <div style={{marginTop: 22, fontSize: 30, color: "rgba(255,255,255,0.82)"}}>تا پایان ۲۰۲۶</div>
        <Euro amount="€63" size={86} />
        <div style={{marginTop: 16, fontSize: 30, color: YELLOW}}>از اول ژانویه ۲۰۲۷</div>
        <Euro amount={grow > 0.98 ? "€66.80" : `€${shown}`} size={92} color={YELLOW} />
        <Bar width={grow * 78} color={WHITE} />
        <Bar width={grow * 86} color={YELLOW} />
      </Copy>
      <Credit text="Sebastian Rittau · CC BY 4.0 · placed, gradient, Persian type" top={1188} />
    </AbsoluteFill>
  );
};

const Bar: React.FC<{width: number; color: string}> = ({width, color}) => (
  <div style={{height: 22, marginTop: 16, background: "rgba(255,255,255,0.16)", borderRadius: 8}}>
    <div style={{width: `${width}%`, height: "100%", background: color, borderRadius: 8}} />
  </div>
);

const DateScene: React.FC<{local: number; still: Still}> = ({local, still}) => {
  const band = still.original ? 1180 : 760;
  const line = interpolate(local, [20, 140], [0, 100], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const second = interpolate(local, [36, 80], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", left: 0, right: 0, top: 0, height: band, overflow: "hidden"}}>
        <StillPlate still={still} local={local} duration={FRAMES[1]} focusX={18} focusY={40} maxHeight={band} />
        <AbsoluteFill style={{background: "linear-gradient(180deg, rgba(11,31,58,0.15), rgba(11,31,58,0.82))"}} />
        <Credit text="Michael F. H. Barth · CC BY-SA 4.0 · placement, gradient, Persian type" top={band - 70} />
      </div>
      <Copy top={band + 36}>
        <div style={{fontSize: 34, color: YELLOW}}>دولت فدرال · نوامبر ۲۰۲۶</div>
        <div style={{marginTop: 16, fontSize: 58, fontWeight: 700, lineHeight: 1.3}}>اجرا از اول ژانویه ۲۰۲۷</div>
        <div style={{height: 10, marginTop: 22, background: "rgba(255,255,255,0.16)", borderRadius: 6}}>
          <div style={{width: `${line}%`, height: "100%", background: YELLOW, borderRadius: 6}} />
        </div>
        <div style={{marginTop: 18, display: "flex", justifyContent: "space-between", direction: "rtl", fontSize: 30}}>
          <span>اعلام</span>
          <span>اول ژانویه ۲۰۲۷</span>
        </div>
        <div style={{marginTop: 22, fontSize: 36, lineHeight: 1.4, opacity: second}}>شاخص قیمت وزرای ترابری ایالت‌ها، اولین بار</div>
        <div style={{marginTop: 28, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, direction: "rtl"}}>
          <div style={{background: "rgba(255,255,255,0.08)", padding: "18px 20px"}}>
            <div style={{fontSize: 26}}>اعلام شد</div>
            <div style={{marginTop: 6, fontSize: 36, fontWeight: 700}}>نوامبر ۲۰۲۶</div>
          </div>
          <div style={{background: YELLOW, color: NAVY, padding: "18px 20px"}}>
            <div style={{fontSize: 26}}>اجرا می‌شود</div>
            <div style={{marginTop: 6, fontSize: 36, fontWeight: 700}}>ژانویه ۲۰۲۷</div>
          </div>
        </div>
      </Copy>
    </AbsoluteFill>
  );
};

const ProviderScene: React.FC<{local: number; still: Still}> = ({local, still}) => {
  const left = interpolate(local, [70, 120], [40, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const right = interpolate(local, [110, 160], [40, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill>
      <StillPlate still={still} local={local} duration={FRAMES[2]} focusX={50} focusY={20} maxHeight={980} />
      <Shade />
      <Copy top={700}>
        <div style={{fontSize: 32, color: YELLOW}}>صفحه دولت فدرال، نه قاعده هر شرکت</div>
        <div style={{marginTop: 8, fontSize: 52, fontWeight: 700, lineHeight: 1.25}}>تأیید تابع شرکت فروشنده است</div>
        <div style={{marginTop: 10, fontSize: 32, lineHeight: 1.35}}>فقط اگر همان شرکت بخواهد، ادامه را باید تأیید کرد.</div>
        <div style={{marginTop: 8, fontSize: 34, fontWeight: 700, color: YELLOW, lineHeight: 1.35}}>
          سکوت، برای هر شرکتی ادامه خودکار نیست.
        </div>
        <div style={{marginTop: 22, display: "flex", gap: 16, direction: "rtl"}}>
          <Chip shift={left} title="دویچه بان" body="می‌پرسد و مهلت دارد" />
          <Chip shift={right} title="ب‌وی‌گ" body="برای اشتراک خودش نمی‌پرسد" />
        </div>
      </Copy>
      <Credit text="Sänger · CC BY-SA 4.0 · placement, gradient, Persian type" top={250} />
    </AbsoluteFill>
  );
};

const Chip: React.FC<{title: string; body: string; shift: number}> = ({title, body, shift}) => (
  <div style={{flex: 1, transform: `translateY(${shift}px)`, background: "rgba(11,31,58,0.72)", borderTop: `8px solid ${YELLOW}`, padding: "16px 18px"}}>
    <div style={{fontSize: 32, fontWeight: 700}}>{title}</div>
    <div style={{marginTop: 6, fontSize: 28, lineHeight: 1.35}}>{body}</div>
  </div>
);

const BahnScene: React.FC<{local: number; still: Still}> = ({local, still}) => {
  const dates = [
    {at: 24, label: "۱۵ اکتبر ۲۰۲۶", note: "سفارش از این تاریخ تأیید جدا نمی‌خواهد"},
    {at: 90, label: "۳۰ نوامبر ۲۰۲۶", note: "مهلت پاسخ برای بلیت به نام دویچه بان"},
    {at: 170, label: "۳۱ دسامبر ۲۰۲۶", note: "بدون پاسخ، همان اشتراک تمام می‌شود"},
  ];
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", left: 0, right: 0, top: 0, height: still.original ? 1920 : 780, overflow: "hidden"}}>
        <StillPlate still={still} local={local} duration={FRAMES[3]} focusX={42} focusY={8} maxHeight={still.original ? 1920 : 780} />
      </div>
      <Shade strong={still.original} />
      <Copy top={still.original ? 250 : 810}>
        <div style={{fontSize: 34, color: YELLOW}}>فقط بلیت‌هایی که دویچه بان به نام خودش فروخته</div>
        <div style={{marginTop: 8, fontSize: 56, fontWeight: 700}}>مهلت دویچه بان</div>
        {dates.map((date) => {
          const shown = interpolate(local, [date.at, date.at + 18], [28, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
          const opacity = interpolate(local, [date.at, date.at + 12], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
          return (
            <div key={date.label} style={{marginTop: 8, opacity, transform: `translateY(${shown}px)`}}>
              <div style={{fontSize: 40, fontWeight: 700, color: YELLOW}}>{date.label}</div>
              <div style={{fontSize: 28, lineHeight: 1.3}}>{date.note}</div>
            </div>
          );
        })}
      </Copy>
      <Credit text="Sebastian Rittau · CC BY 4.0 · upper crop at 1.125x, gradient, Persian type" top={still.original ? 1188 : 730} />
    </AbsoluteFill>
  );
};

const BvgScene: React.FC<{local: number}> = ({local}) => {
  const slide = interpolate(local, [8, 28], [80, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const amount = interpolate(local, [36, 80], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", inset: 0, display: "flex"}}>
        <div style={{width: "38%", background: YELLOW, color: NAVY, transform: `translateX(${-slide}px)`, padding: "520px 36px 0", fontFamily: "Vazirmatn, sans-serif"}}>
          <div style={{fontSize: 72, fontWeight: 700, opacity: amount, direction: "ltr"}}>€66.80</div>
        </div>
        <div style={{flex: 1, background: NAVY, transform: `translateX(${slide}px)`}} />
      </div>
      <div style={{position: "absolute", top: 280, left: 500, right: 72, direction: "rtl", textAlign: "right"}}>
        <div style={{fontSize: 32, color: YELLOW}}>دو شرکت، دو قاعده</div>
        <div style={{marginTop: 24, fontSize: 44, fontWeight: 700}}>دویچه بان پاسخ می‌خواهد</div>
        <div style={{marginTop: 22, fontSize: 52, fontWeight: 700, color: YELLOW, lineHeight: 1.3}}>ب‌وی‌گ تأیید نمی‌خواهد</div>
        <div style={{marginTop: 16, fontSize: 34, lineHeight: 1.4, opacity: amount}}>
          مبلغ اشتراک ب‌وی‌گ خودکار <span style={{direction: "ltr", unicodeBidi: "isolate"}}>€66.80</span> می‌شود
        </div>
      </div>
    </AbsoluteFill>
  );
};

const CloseScene: React.FC<{local: number; still: Still}> = ({local, still}) => {
  const rise = interpolate(local, [0, 18], [24, 0], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill>
      <StillPlate still={still} local={local} duration={FRAMES[5]} focusX={50} focusY={62} maxHeight={1100} />
      <Shade />
      <Copy top={1080 + rise}>
        <div style={{fontSize: 48, fontWeight: 700, lineHeight: 1.3}}>یک قاعده برای هر فروشنده نیست</div>
      </Copy>
      <Credit text="Sänger · CC BY-SA 4.0 · adapted photograph remains CC BY-SA 4.0" top={980} />
    </AbsoluteFill>
  );
};

const CAPTIONS: {at: number; text: string}[][] = [
  [
    {at: 0, text: "از اول ژانویه ۲۰۲۷ قیمت ماهانه از \u2066€63\u2069 به \u2066€66.80\u2069 می‌رسد."},
    {at: 270, text: "این فقط خبر گرانی نیست."},
  ],
  [
    {at: 0, text: "دولت فدرال این قیمت را برای اول ژانویه ۲۰۲۷ نوشته است."},
    {at: 230, text: "شاخص قیمت وزرای ترابری ایالت‌ها اولین بار به کار می‌افتد."},
  ],
  [
    {at: 0, text: "تأیید فقط وقتی لازم است که همان شرکت آن را بخواهد."},
    {at: 210, text: "صفحه دولت از اعمال خودکار می‌گوید. این برای هر شرکتی نیست."},
  ],
  [
    {at: 0, text: "دویچه بان تا ۳۰ نوامبر ۲۰۲۶ پاسخ می‌خواهد. بدون پاسخ، اشتراک در ۳۱ دسامبر تمام می‌شود."},
    {at: 300, text: "خرید از ۱۵ اکتبر ۲۰۲۶ پیش دویچه بان تأیید جدا نمی‌خواهد."},
  ],
  [{at: 0, text: "ب‌وی‌گ می‌گوید برای اشتراک خودش تأیید لازم نیست و مبلغ خودکار به \u2066€66.80\u2069 می‌رسد."}],
  [
    {at: 0, text: "یک قاعده برای هر فروشنده نیست."},
    {at: 90, text: "پیام همان شرکتی را بخوان که بلیت را از آن گرفته‌ای."},
  ],
];

const Caption: React.FC<{index: number; local: number}> = ({index, local}) => {
  const lines = CAPTIONS[index];
  const text = [...lines].reverse().find((line) => local >= line.at)?.text ?? lines[0].text;
  return (
    <div
      style={{
        position: "absolute",
        left: 64,
        right: 160,
        bottom: 430,
        direction: "rtl",
        textAlign: "right",
        fontSize: 42,
        fontWeight: 700,
        lineHeight: 1.4,
        color: WHITE,
        backgroundColor: "rgba(11,31,58,0.9)",
        borderRight: `10px solid ${YELLOW}`,
        padding: "18px 22px",
      }}
    >
      {text}
    </div>
  );
};

export const PHOTO_TICKET_FRAMES = TOTAL;
