package svc

// Repo persists names.
type Repo struct{}

// Save stores one name.
func (r *Repo) Save(name string) error {
	return nil
}
