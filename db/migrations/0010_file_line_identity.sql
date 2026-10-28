-- M7 review: a file is tied to a quote line by its number, and staff can edit, remove or reorder
-- lines afterwards. Record the part name the file was uploaded for, so code can tell when the
-- line it points at is no longer the same part (or material) and ask for the file again.
ALTER TABLE files ADD COLUMN part_name text;
