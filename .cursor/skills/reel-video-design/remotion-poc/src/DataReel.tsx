import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

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

export type DataScene = {
  durationFrames: number;
  headline: string;
  caption: string;
  /** Path relative to Remotion public/, staged by the Python renderer. */
  image?: string;
  credit?: string;
  /** When true (or image missing), draw a simple navy graphic plate. */
  graphic?: boolean;
};

export type DataReelProps = {
  scenes: DataScene[];
  /** Path relative to Remotion public/ for the narration MP3. */
  audioFile?: string;
};

const ScenePlate: React.FC<{scene: DataScene}> = ({scene}) => {
  const frame = useCurrentFrame();
  const duration = Math.max(scene.durationFrames, 1);
  const fadeIn = interpolate(frame, [0, 10], [0, 1], {extrapolateRight: "clamp"});
  const scale = interpolate(frame, [0, duration], [1, 1.06], {extrapolateRight: "clamp"});
  const drift = interpolate(frame, [0, duration], [0, 28], {extrapolateRight: "clamp"});
  const usePhoto = Boolean(scene.image) && !scene.graphic;

  return (
    <AbsoluteFill style={{opacity: fadeIn}}>
      {usePhoto ? (
        <Img
          src={staticFile(scene.image as string)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${scale}) translateX(${drift * -0.15}px)`,
          }}
        />
      ) : (
        <AbsoluteFill
          style={{
            background: `linear-gradient(160deg, ${NAVY} 0%, #15345c 55%, #0a1830 100%)`,
          }}
        >
          <div
            style={{
              position: "absolute",
              top: 220,
              left: 80,
              right: 80,
              height: 18,
              background: YELLOW,
              opacity: 0.9,
              transform: `translateX(${drift}px)`,
            }}
          />
          <div
            style={{
              position: "absolute",
              top: 520,
              left: 120,
              width: 220,
              height: 220,
              border: `6px solid ${YELLOW}`,
              opacity: 0.55,
              transform: `scale(${scale})`,
            }}
          />
        </AbsoluteFill>
      )}
      <AbsoluteFill
        style={{
          background: "linear-gradient(180deg, rgba(11,31,58,0.2), rgba(11,31,58,0.9))",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 280,
          left: 72,
          right: 72,
          color: WHITE,
          fontSize: 58,
          fontWeight: 700,
          lineHeight: 1.35,
          textAlign: "right",
          direction: "rtl",
          fontFamily: "Vazirmatn, sans-serif",
          whiteSpace: "pre-line",
        }}
      >
        {scene.headline}
      </div>
      {scene.credit ? (
        <div
          style={{
            position: "absolute",
            top: 1180,
            left: 72,
            right: 72,
            color: WHITE,
            fontSize: 22,
            textAlign: "left",
            direction: "ltr",
            opacity: 0.85,
            fontFamily: "Vazirmatn, sans-serif",
          }}
        >
          {scene.credit}
        </div>
      ) : null}
      <div
        style={{
          position: "absolute",
          left: 64,
          right: 64,
          bottom: 360,
          background: "rgba(11,31,58,0.92)",
          color: WHITE,
          fontSize: 36,
          fontWeight: 700,
          lineHeight: 1.45,
          textAlign: "right",
          direction: "rtl",
          fontFamily: "Vazirmatn, sans-serif",
          padding: 24,
          borderRight: `8px solid ${YELLOW}`,
        }}
      >
        {scene.caption}
      </div>
      <div
        style={{
          position: "absolute",
          left: 64,
          right: 64,
          bottom: 120,
          color: "rgba(255,255,255,0.7)",
          fontSize: 22,
          textAlign: "right",
          direction: "rtl",
          fontFamily: "Vazirmatn, sans-serif",
        }}
      >
        تصاویر و طرح‌ها توضیحی‌اند، نه فیلم رویداد.
      </div>
    </AbsoluteFill>
  );
};

export const DataReel: React.FC<DataReelProps> = ({scenes, audioFile}) => {
  const {fps} = useVideoConfig();
  let cursor = 0;
  return (
    <AbsoluteFill style={{backgroundColor: NAVY, fontFamily: "Vazirmatn, sans-serif"}}>
      <style>{fontFace}</style>
      {audioFile ? <Audio src={staticFile(audioFile)} /> : null}
      {scenes.map((scene, index) => {
        const from = cursor;
        const duration = Math.max(1, Math.round(scene.durationFrames || 0));
        cursor += duration;
        return (
          <Sequence key={index} from={from} durationInFrames={duration} name={`scene-${index + 1}`}>
            <ScenePlate scene={{...scene, durationFrames: duration}} />
          </Sequence>
        );
      })}
      <div style={{display: "none"}}>{fps}</div>
    </AbsoluteFill>
  );
};

export function dataReelDuration(scenes: DataScene[]): number {
  return Math.max(
    scenes.reduce((sum, scene) => sum + Math.max(1, Math.round(scene.durationFrames || 0)), 0),
    1,
  );
}
