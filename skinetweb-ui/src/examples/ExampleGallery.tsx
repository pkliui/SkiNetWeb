import { urlToFile } from "../utils/imageUtils";

type LesionExample = { id: string; label: string; src: string };
type LesionGroup   = { group: string; items: LesionExample[] };

const LESION_GROUPS: LesionGroup[] = [
  {
    group: "Malignant",
    items: [
      { id: "IMD285_melanoma",         label: "Melanoma",          src: "/examples/IMD285_melanoma.png" },
    ],
  },
  {
    group: "Benign",
    items: [
      { id: "IMD002_atypical_nevus",   label: "Atypical nevus",    src: "/examples/IMD002_atypical_nevus.png" },
      { id: "IMD004_atypical_nevus",   label: "Atypical nevus",    src: "/examples/IMD004_atypical_nevus.png" },
      { id: "IMD016_common_nevus",     label: "Common nevus",      src: "/examples/IMD016_common_nevus.png" },
      { id: "IMD025_common_nevus",     label: "Common nevus",      src: "/examples/IMD025_common_nevus.png" },
      { id: "IMD078_intradermal_nevus",label: "Intradermal nevus", src: "/examples/IMD078_intradermal_nevus.png" },
    ],
  },
];

type Props = { onFileSelect: (file: File) => void };

const ExampleGallery = ({ onFileSelect }: Props) => {
  const select = async (src: string, filename: string) => {
    try {
      onFileSelect(await urlToFile(src, filename));
    } catch {
      console.error("Failed to load example image:", src);
    }
  };

  return (
    <aside className="gallery-sidebar">
      <p className="gallery-title">Examples</p>
      <p className="gallery-hint">Drag to zone or click</p>

      {LESION_GROUPS.map(({ group, items }) => (
        <div key={group} className="gallery-group">
          <p className="gallery-group-label">{group}</p>
          <ul className="gallery-list">
            {items.map(({ id, label, src }) => (
              <li key={id} className="gallery-item">
                <img
                  src={src}
                  alt={label}
                  className="gallery-thumb"
                  draggable
                  onDragStart={(e) => e.dataTransfer.setData("x-example-url", src)}
                  onClick={() => select(src, `${id}.png`)}
                />
                <span className="gallery-label">{label}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </aside>
  );
};

export default ExampleGallery;
