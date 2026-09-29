package svc

type Service struct {
	repo *Repo
}

func NewService() *Service {
	return &Service{repo: &Repo{}}
}

func (s *Service) Handle(name string) error {
	return s.repo.Save(name)
}
