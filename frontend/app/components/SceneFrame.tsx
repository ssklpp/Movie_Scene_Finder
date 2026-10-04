"use client";

import { useRef, useState } from "react";

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const IMAGE_TYPES = ["image/jpeg", "image/png"];

type Props = {
  text: string;
  onTextChange: (text: string) => void;
  image: File | null;
  onImageChange: (image: File | null) => void;
  onSubmit: () => void;
  onImageError: (message: string) => void;
  disabled: boolean;
};

/**
 * 영화 화면 모양의 입력란. 기억은 화면 아래 자막처럼 적고, 사진은 화면 위에 끌어다 놓는다.
 */
export default function SceneFrame({
  text,
  onTextChange,
  image,
  onImageChange,
  onSubmit,
  onImageError,
  disabled,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  // 미리보기 주소는 사진을 고르거나 뺄 때 만들고 해제한다.
  const [preview, setPreview] = useState<string | null>(null);

  function setPhoto(file: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setPreview(file ? URL.createObjectURL(file) : null);
    onImageChange(file);
  }

  function pick(file: File | undefined) {
    if (!file) return;
    if (!IMAGE_TYPES.includes(file.type)) {
      onImageError("사진은 JPEG이나 PNG만 올릴 수 있어요.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      onImageError("사진은 5MB 이하만 올릴 수 있어요.");
      return;
    }
    setPhoto(file);
  }

  return (
    <div
      className={`relative overflow-hidden rounded-sm border-[6px] bg-screen ${
        dragging ? "border-subtitle" : "border-screen-edge"
      } aspect-[4/3] sm:aspect-[2.39/1]`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!disabled) pick(e.dataTransfer.files[0]);
      }}
    >
      {preview ? (
        // eslint-disable-next-line @next/next/no-img-element -- 브라우저에만 있는 미리보기(blob URL)
        <img
          src={preview}
          alt="올린 사진"
          className="absolute inset-0 h-full w-full object-cover opacity-80"
        />
      ) : (
        <p className="absolute inset-x-0 top-[30%] text-center text-sm text-white/45">
          {dragging ? (
            "여기에 놓으면 사진으로도 찾아요"
          ) : (
            <>
              장면 사진이 있으면 올려도 돼요
              <span className="hidden sm:inline">. 여기에 끌어다 놓아도 돼요</span>
            </>
          )}
        </p>
      )}

      <div className="absolute right-3 top-3 flex gap-2">
        <input
          ref={fileInput}
          type="file"
          accept="image/jpeg,image/png"
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        {image ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => setPhoto(null)}
            className="rounded-sm bg-black/50 px-3 py-1.5 text-sm text-white hover:bg-black/70 disabled:opacity-50"
          >
            사진 빼기
          </button>
        ) : (
          <button
            type="button"
            disabled={disabled}
            onClick={() => fileInput.current?.click()}
            className="rounded-sm bg-black/35 px-3 py-1.5 text-sm text-white/90 hover:bg-black/60 disabled:opacity-50"
          >
            사진 올리기
          </button>
        )}
      </div>

      <label htmlFor="memory" className="sr-only">
        기억나는 장면
      </label>
      <textarea
        id="memory"
        value={text}
        disabled={disabled}
        onChange={(e) => onTextChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onSubmit();
        }}
        rows={2}
        maxLength={300}
        placeholder="비 오는 밤, 가족이 긴 계단을 한참 내려가던 장면"
        className="subtitle-text absolute inset-x-0 bottom-0 w-full resize-none bg-transparent px-6 pb-6 pt-2 text-center text-lg font-medium leading-snug outline-none sm:px-16 sm:text-2xl"
      />
    </div>
  );
}
