import { useState, useEffect } from "react";
import "./App.css";

// give notes a type 
type Note = {
  id: number;
  title: string;
  content: string;
}

const App = () => {
  //
  // set states
  //
  // store all notes inside a state and give note the Note type,you may initialize using a dummy array

  // set of dummy notes
  const [notes, setNotes] = useState<Note[]>([]);
    
  //
  // set state variables
  //
  // use state variables for form inputs
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  // state variable for a selected note (null because we not not have selected any note)
  const [selectedNote, setSelectedNote] = useState<Note | null>(null);


  // set up API stuff
  useEffect(()=> {
    // get notes from DB
    const fetchNotes = async() => {
      try{
        const response = await fetch("http://localhost:5000/api/notes")
        const notes: Note[] = await response.json()
        // update notes we just got rom API
        setNotes(notes)
      } catch(e){
        // handle errors that may come from API
        console.log(e);
      }
    };
    fetchNotes();
  }, []);


  //
  // set handlers
  //
  // handle a click on a note - accepts a note that the user clicked on
  // to actually know what the selected note (potentially up for a change) is
  const handleNoteClick = (note: Note) => {
    // no need to create a new note, just get the selected one
    // update title and content accordingly
    setSelectedNote(note);
    setTitle(note.title);
    setContent(note.content);
  };


  const handleAddNote = async (event: React.FormEvent) => {
    // take in event as param, need to say this is of type FormEvent, otherwise TS will complain
    // add preventDefault to prevent from reloading the page upon submitting!
    event.preventDefault();

    // create a new note
    // const newNote: Note = {
    //   id: notes.length + 1,
    //   title: title,
    //   content: content
    // }

    try{
      const response = await fetch
      ("http://localhost:5000/api/notes",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            title,
            content
          })
        }
       );

      // receive the note we just posted
      const newNote = await response.json();

    // update the state with this note,
    // pass new array - the (1st) one we just created and the rest of the notes
    setNotes([newNote, ...notes]);
    // clean up the submission forms for a nice UI
    setTitle("");
    setContent("");
      }
      catch(error){
        console.log(error);
      }
  };


  // update a selected note
  const handleUpdateNote = async (
    event: React.FormEvent
  ) => {
    event.preventDefault();
    if(!selectedNote){
      return;
    }

    if(!selectedNote){
      return; // if no selected note, just return a function
    }

    // actually update the note
    try{
      const response = await fetch
      (`http://localhost:5000/api/notes/${selectedNote.id}`,
        {
          method: 'PUT',
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            title,
            content
          })
        }
      )

      // receive the note we just updated
      const updatedNote = await response.json();

      // map function runs thru an array and now we check if we need to update the note (if the id matched selected id)
      const updatedNotesList = notes.map((note)=>
        note.id === selectedNote.id // if matches
        ? updatedNote // update the note
        : note
      )
      // update the notes' state
      setNotes(updatedNotesList)
      // upfate the submission form's title and content
      setTitle("")
      setContent("")
      setSelectedNote(null)
    }catch(error){
      console.log(error);
    }
  };


  // reset form
  const handleCancel = (event: React.FormEvent) =>{
    setTitle("")
    setContent("")
    setSelectedNote(null);
  }


  // delete a note
  const deleteNote = async (
    event: React.MouseEvent,
    noteId: number
  ) => {
    event.stopPropagation();
    try{
      await fetch(`http://localhost:5000/api/notes/${noteId}`,
        {
          method:"DELETE",
        })
        }catch(e){
    }

    // get the filtered notes list
    const filteredNotesList = notes.filter(
      (note) => note.id !== noteId)
    // update the notes' state
    setNotes(filteredNotesList);
  }


  return (
    <div className="app-container">
      <h1 className="app-title">The Green Notes App</h1>
      {/* 
      // set up a submission form for notes 
      */}
      <form className="note-form"
        // wire up the submit function to the form
        onSubmit={(event) => 
          selectedNote
          ? handleUpdateNote(event)
          : handleAddNote(event)
        }
      >
        {/* 
        // set up form's title and content area
        */}
        <input 
          // title input - binded to the title state variable = whatever title state variable is
          value={title}
          onChange={(event)=>
            setTitle(event.target.value)
          }
          placeholder="What do you want to note?" required
        />
        <textarea 
          // text area - binded to the content state variable
          value={content}
          onChange={(event)=> setContent(event.target.value)
        }
          placeholder="Anything else you forgot to add?" rows={10}
        />

        {selectedNote ? (
            // handle button logic depending if a note was selected or not 
            <div className="edit-buttons">
              <button type="submit">Save</button>
              <button onClick={handleCancel}>Cancel</button>
            </div>
          ):(
            <button type="submit">Add Note</button>)}      
      </form>
      
      {/* 
      Notes grid
      */}
      <div className="notes-grid">
        {notes.map((note) => (
          //Display all notes using the markup below by means of the map function
          <div className="note-item"
            // add an existing note on a click
            onClick={() => handleNoteClick(note)}
          >
            <div className="notes-header"  onClick={() => handleNoteClick(note)}
                // add an existing note on a click
            >
              <button
                // delete button
                onClick={(event) => 
                  deleteNote(event, note.id)
                }>x</button>
            </div>
            <h2>{note.title}</h2>
            <p>{note.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default App;