namespace Proj.Svc
{
    public class Service
    {
        private readonly Repo repo = new Repo();

        public bool Handle(string name)
        {
            return repo.Save(name);
        }
    }
}
