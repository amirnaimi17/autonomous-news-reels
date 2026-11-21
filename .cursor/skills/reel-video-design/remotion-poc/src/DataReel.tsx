import React from "react";
import {AbsoluteFill, Img, Sequence, staticFile, useVideoConfig} from "remotion";

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
  image?: string;
  credit?: string;
};

export const DataReel: React.FC<{scenes: DataScene[]}> = ({scenes}) => {
  const {fps} = useVideoConfig();
  let cursor = 0;
  return (
    <AbsoluteFill style={{backgroundColor: NAVY, fontFamily: "Vazirmatn"}}>
      <style>{fontFace}</style>
      {scenes.map((scene, index) => {
        const from = cursor;
        cursor += scene.durationFrames;
        return (
          <Sequence key={index} from={from} durationInFrames={scene.durationFrames} name={`scene-${index + 1}`}>
            <AbsoluteFill>
              {scene.image ? (
                <Img src={staticFile(scene.image)} style={{width: "100%", height: "100%", objectFit: "cover"}} />
              ) : null}
              <AbsoluteFill style={{background: "linear-gradient(180deg, rgba(11,31,58,0.15), rgba(11,31,58,0.88))"}} />
              <div style={{position: "absolute", top: 280, left: 72, right: 160, color: WHITE, fontSize: 64, fontWeight: 700, textAlign: "right", direction: "rtl"}}>
                {scene.headline}
              </div>
              {scene.credit ? (
                <div style={{position: "absolute", top: 1180, left: 72, right: 160, color: WHITE, fontSize: 22}}>
                  {scene.credit}
                </div>
              ) : null}
              <div style={{position: "absolute", left: 64, right: 160, bottom: 430, background: "rgba(11,31,58,0.9)", color: WHITE, fontSize: 42, fontWeight: 700, textAlign: "right", direction: "rtl", padding: 24, borderRight: `8px solid ${YELLOW}`}}>
                {scene.caption}
              </div>
            </AbsoluteFill>
          </Sequence>
        );
      })}
      <div style={{display: "none"}}>{fps}</div>
    </AbsoluteFill>
  );
};

export function dataReelDuration(scenes: DataScene[]): number {
  return Math.max(scenes.reduce((sum, scene) => sum + (scene.durationFrames || 0), 0), 1);
}
